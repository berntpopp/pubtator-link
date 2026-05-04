"""Fixture payloads for literature graph provider tests."""

CROSSREF_WORK_ARD_2025 = {
    "message": {
        "DOI": "10.1016/j.ard.2025.05.020",
        "title": ["A closed review article"],
        "container-title": ["Annals of the Rheumatic Diseases"],
        "published-print": {"date-parts": [[2025, 5]]},
        "reference": [
            {
                "DOI": "10.1000/primary-study",
                "article-title": "Primary trial of colchicine",
                "journal-title": "Example Journal",
                "year": "2021",
            },
            {
                "article-title": "Unresolved guideline reference",
                "journal-title": "Guideline Journal",
                "year": "2019",
            },
        ],
    }
}

EUROPE_PMC_CITATIONS_40562663 = {
    "resultList": {
        "result": [
            {
                "id": "40600001",
                "pmid": "40600001",
                "doi": "10.1000/citing-study",
                "title": "Citing accessible study",
                "journalTitle": "Open Journal",
                "pubYear": "2026",
                "pmcid": "PMC40600001",
                "isOpenAccess": "Y",
                "inPMC": "Y",
                "hasPDF": "Y",
            }
        ]
    }
}

OPENALEX_WORK = {
    "id": "https://openalex.org/W123",
    "doi": "https://doi.org/10.1000/primary-study",
    "pmid": "https://pubmed.ncbi.nlm.nih.gov/39596913",
    "title": "Primary trial of colchicine",
    "publication_year": 2021,
    "primary_location": {"source": {"display_name": "Example Journal"}},
    "open_access": {
        "is_oa": True,
        "oa_status": "green",
        "oa_url": "https://example.org/fulltext",
    },
    "referenced_works": ["https://openalex.org/W999"],
    "related_works": ["https://openalex.org/W888"],
    "cited_by_api_url": "https://api.openalex.org/works?filter=cites:W123",
    "authorships": [
        {
            "author": {
                "id": "https://openalex.org/A1",
                "display_name": "Ada Example",
                "orcid": "https://orcid.org/0000-0001-0000-0000",
            },
            "institutions": [{"display_name": "Example University"}],
        }
    ],
}

UNPAYWALL_WORK = {
    "doi": "10.1000/primary-study",
    "oa_status": "green",
    "is_oa": True,
    "best_oa_location": {
        "url": "https://example.org/fulltext",
        "license": "cc-by",
    },
}

NCBI_ELINK_NEIGHBOR_SCORE = {
    "linksets": [
        {
            "ids": ["40562663"],
            "linksetdbs": [
                {
                    "linkname": "pubmed_pubmed",
                    "links": [
                        {"id": "39596913", "score": 1220},
                        {"id": "40600001", "score": 900},
                    ],
                }
            ],
        }
    ]
}
