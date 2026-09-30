"""Step-2 acceptance: all six tools work on cached/fixtures data (offline)."""

import json
from pathlib import Path

import pytest

from mito_harness.schemas import (
    Direction,
    DirectionPlotItem,
    EvidenceLevel,
    GapCell,
    ProspectsComponent,
    ProspectsItem,
)
from mito_harness.tools.compute_plot import (
    effect_direction_plot,
    evidence_gap_map,
    prospects_ranking,
)
from mito_harness.tools.ctgov_search import parse_ctgov
from mito_harness.tools.europepmc_search import parse_europepmc
from mito_harness.tools.parse_record import parse_record
from mito_harness.tools.pubmed_search import parse_pubmed_xml

PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>36100001</PMID>
      <Article>
        <Journal>
          <ISOAbbreviation>J Mitochondr Med</ISOAbbreviation>
          <JournalIssue><PubDate><Year>2022</Year></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>Elamipretide improves mitochondrial function in heart failure: a randomized trial.</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Heart failure features mitochondrial dysfunction.</AbstractText>
          <AbstractText Label="RESULTS">Six-minute walk distance improved by 25 m (p=0.03).</AbstractText>
        </Abstract>
        <PublicationType>Randomized Controlled Trial</PublicationType>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/fake.2022</ArticleId></ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""

EPMC_JSON = {
    "resultList": {
        "result": [
            {
                "title": "Urolithin A and mitophagy in aging muscle.",
                "abstractText": "Objective: to assess urolithin A effects.",
                "journalTitle": "Aging Cell",
                "pubYear": "2023",
                "pmid": "36700002",
                "doi": "10.1111/acel.2023",
                "pubTypeList": {"pubType": [{"name": "Clinical Trial"}]},
            },
            {"title": "", "abstractText": "should be skipped"},
        ]
    }
}

CTGOV_JSON = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT04567890",
                    "briefTitle": "MitoQ in Parkinson's disease",
                },
                "statusModule": {"startDateStruct": {"date": "2022-05-01"}},
                "designModule": {"phases": ["PHASE2"], "enrollmentInfo": {"count": "120"}},
                "descriptionModule": {"briefSummary": "A phase 2 study of MitoQ."},
            }
        }
    ]
}


def test_parse_pubmed_xml():
    records = parse_pubmed_xml(PUBMED_XML)
    assert len(records) == 1
    rec = records[0]
    assert rec.pmid == "36100001"
    assert rec.year == 2022
    assert rec.doi == "10.1000/fake.2022"
    assert "Randomized Controlled Trial" in rec.pubtypes
    assert "BACKGROUND:" in (rec.abstract or "")
    assert rec.ref_id == "36100001"


def test_parse_europepmc():
    records = parse_europepmc(EPMC_JSON)
    assert len(records) == 1
    rec = records[0]
    assert rec.pmid == "36700002"
    assert rec.year == 2023
    assert rec.journal == "Aging Cell"


def test_parse_ctgov():
    records = parse_ctgov(CTGOV_JSON)
    assert len(records) == 1
    rec = records[0]
    assert rec.nct_id == "NCT04567890"
    assert rec.trial_phase == "PHASE2"
    assert rec.enrollment == 120
    assert rec.year == 2022


RAW_EXTRACTION = {
    "ref_id": "36100001",
    "title": "Elamipretide improves mitochondrial function in heart failure: a randomized trial.",
    "source": "pubmed",
    "intervention": "elamipretide",
    "intervention_class": "cardiolipin-binding peptide",
    "target": "cardiolipin",
    "disease": "chronic heart failure",
    "is_standard_of_care": False,
    "design": "randomized placebo-controlled trial",
    "phase": "Phase 2",
    "n_participants": 50,
    "outcomes": [
        {
            "name": "6-minute walk distance",
            "direction": "improved",
            "significant": True,
            "effect_text": "+25 m (p=0.03)",
            "favors": "intervention",
        }
    ],
    "evidence_level": "rct",
    "year": 2022,
}


def test_parse_record_normalizes():
    rec = parse_record(RAW_EXTRACTION)
    assert rec.phase.value == "phase2"
    assert rec.outcomes[0].direction is Direction.positive
    assert rec.evidence_level is EvidenceLevel.rct


def test_parse_record_rejects_bad_ref():
    bad = dict(RAW_EXTRACTION, ref_id="not-an-id")
    with pytest.raises(ValueError, match="ref_id"):
        parse_record(bad)


def test_parse_record_rejects_bad_direction():
    bad = json.loads(json.dumps(RAW_EXTRACTION))
    bad["outcomes"][0]["direction"] = "sideways"
    with pytest.raises(ValueError, match="direction"):
        parse_record(bad)


@pytest.mark.asyncio
async def test_verify_citation_via_cache_replay(tmp_path, monkeypatch):
    """Offline: pre-seed the disk cache, verify_citation replays it without network."""
    import importlib

    import setting

    vc = importlib.import_module("mito_harness.tools.verify_citation")

    class FakePaths:
        cache_dir = tmp_path

    class FakeSettings:
        paths = FakePaths()
        sources = setting.get_settings().sources
        ncbi_api_key = None

    monkeypatch.setattr(vc, "get_settings", lambda: FakeSettings())

    # seed the pubmed esummary cache exactly as SourceClient would
    from mito_harness.cache import DiskCache

    cache = DiskCache(tmp_path)
    cache.set(
        "pubmed",
        {
            "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            "params": {"db": "pubmed", "id": "36100001", "retmode": "json"},
        },
        {
            "result": {
                "36100001": {
                    "title": "Elamipretide improves mitochondrial function in heart failure: a randomized trial.",
                    "pubdate": "2022 Sep",
                }
            }
        },
    )

    claimed = "Elamipretide improves mitochondrial function in heart failure: a randomized trial."
    result = await vc.verify_citation("36100001", claimed, 2022)
    assert result.verified
    assert result.title_similarity > 0.99

    result_bad = await vc.verify_citation("36100001", "Completely different invented title about something else")
    assert not result_bad.verified
    assert "mismatch" in result_bad.reason


def _plot_items():
    return [
        DirectionPlotItem(
            study_label="MMPOWER-3 (Ph2)",
            outcome="6MWT change",
            arm="mito",
            direction=Direction.positive,
            significant=False,
            evidence=EvidenceLevel.rct,
            ref_id="NCT02805790",
        ),
        DirectionPlotItem(
            study_label="MMPOWER-3 (Ph2)",
            outcome="6MWT change",
            arm="standard",
            direction=Direction.neutral,
            significant=False,
            evidence=EvidenceLevel.rct,
            ref_id="NCT02805790",
        ),
        DirectionPlotItem(
            study_label="RESCUE (Ph3)",
            outcome="BCVA change",
            arm="mito",
            direction=Direction.positive,
            significant=True,
            evidence=EvidenceLevel.rct,
            ref_id="NCT03295071",
        ),
        DirectionPlotItem(
            study_label="IMPACT-HFpEF (Ph2)",
            outcome="VO2 peak",
            arm="mito",
            direction=Direction.negative,
            significant=True,
            evidence=EvidenceLevel.rct,
            ref_id="NCT02800097",
        ),
        DirectionPlotItem(
            study_label="IMPACT-HFpEF (Ph2)",
            outcome="QoL score",
            arm="mito",
            direction=Direction.unclear,
            significant=False,
            evidence=EvidenceLevel.observational,
            ref_id="NCT02800097",
        ),
    ]


def test_three_plots_produced(tmp_path: Path):
    p1 = effect_direction_plot(_plot_items(), tmp_path / "direction.png", "Mito vs standard")
    p2 = prospects_ranking(
        [
            ProspectsItem(
                label="elamipretide",
                total=7.1,
                components=[
                    ProspectsComponent(name="phase", score=8, weight=0.3),
                    ProspectsComponent(name="effect", score=6, weight=0.4),
                    ProspectsComponent(name="unmet need", score=8, weight=0.3),
                ],
            ),
            ProspectsItem(
                label="SkQ1",
                total=3.2,
                components=[
                    ProspectsComponent(name="phase", score=3, weight=0.3),
                    ProspectsComponent(name="effect", score=4, weight=0.4),
                    ProspectsComponent(name="unmet need", score=2, weight=0.3),
                ],
            ),
        ],
        tmp_path / "prospects.png",
        "Direction ranking",
    )
    p3 = evidence_gap_map(
        [
            GapCell(
                intervention="elamipretide", disease="PMD", n_studies=3, top_evidence=EvidenceLevel.rct, refs=["NCT1"]
            ),
            GapCell(
                intervention="SkQ1", disease="HF", n_studies=1, top_evidence=EvidenceLevel.preclinical, refs=["PM1"]
            ),
        ],
        tmp_path / "gapmap.png",
        "Evidence gap map",
    )
    for png in (p1, p2, p3):
        assert png.exists() and png.stat().st_size > 10_000
