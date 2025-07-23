"""Mock API response fixtures for PubTator3 API testing."""

from typing import Dict, List, Any


class MockPubTatorResponses:
    """Collection of mock PubTator3 API responses for testing."""

    @staticmethod
    def publication_export_biocjson() -> Dict[str, Any]:
        """Mock publication export response in biocjson format."""
        return {
            "PubTator3": [
                {
                    "_id": "29355051|None",
                    "id": "29355051",
                    "infons": {},
                    "passages": [
                        {
                            "infons": {
                                "journal": "Integr Cancer Ther. 2018 Sep;17(3):860-866.",
                                "year": "2018",
                                "type": "title",
                                "authors": "Deng X, Luo S",
                            },
                            "offset": 0,
                            "text": "Fraction From Lycium barbarum Polysaccharides Reduces Oxidative Stress.",
                            "sentences": [],
                            "annotations": [
                                {
                                    "id": "1",
                                    "infons": {
                                        "identifier": "112863",
                                        "type": "Species",
                                        "valid": True,
                                        "normalized": ["112863"],
                                        "database": "ncbi_taxonomy",
                                        "normalized_id": "112863",
                                        "biotype": "species",
                                        "name": "Lycium barbarum",
                                        "accession": "@SPECIES_Lycium_barbarum",
                                    },
                                    "text": "Lycium barbarum",
                                    "locations": [{"offset": 14, "length": 15}],
                                }
                            ],
                            "relations": [],
                        },
                        {
                            "infons": {"type": "abstract"},
                            "offset": 72,
                            "text": (
                                "This study investigates the antioxidant properties of "
                                "polysaccharides extracted from Lycium barbarum."
                            ),
                            "sentences": [],
                            "annotations": [
                                {
                                    "id": "2",
                                    "infons": {
                                        "identifier": "112863",
                                        "type": "Species",
                                        "valid": True,
                                        "normalized": ["112863"],
                                        "database": "ncbi_taxonomy",
                                        "normalized_id": "112863",
                                        "biotype": "species",
                                        "name": "Lycium barbarum",
                                        "accession": "@SPECIES_Lycium_barbarum",
                                    },
                                    "text": "Lycium barbarum",
                                    "locations": [{"offset": 158, "length": 15}],
                                }
                            ],
                            "relations": [],
                        },
                    ],
                    "relations": [],
                    "pmid": 29355051,
                    "pmcid": None,
                    "meta": {},
                    "date": "2018-09-01T00:00:00Z",
                    "journal": "Integr Cancer Ther",
                    "authors": ["Deng X", "Luo S", "Chen Y"],
                    "relations_display": [],
                }
            ]
        }

    @staticmethod
    def publication_export_pubtator() -> Dict[str, str]:
        """Mock publication export response in pubtator format."""
        return {
            "content": (
                "29355051|t|Fraction From Lycium barbarum Polysaccharides Reduces Oxidative Stress\n"
                "29355051|a|This study investigates the antioxidant properties of "
                "polysaccharides extracted from Lycium barbarum.\n"
                "29355051\t14\t29\tLycium barbarum\tSpecies\t112863\n"
                "29355051\t158\t173\tLycium barbarum\tSpecies\t112863\n"
                "\n"
                "32511357|t|BRCA1 mutations and breast cancer susceptibility\n"
                "32511357|a|Analysis of BRCA1 gene mutations in hereditary breast cancer patients.\n"
                "32511357\t0\t5\tBRCA1\tGene\t672\n"
                "32511357\t10\t19\tmutations\tVariant\tTMVar:tmVar:p|SUB|A|1|G;HGVS:p.A1G;VariO:0001\n"
                "32511357\t24\t37\tbreast cancer\tDisease\tMESH:D001943\n"
            )
        }

    @staticmethod
    def publication_export_biocxml() -> Dict[str, str]:
        """Mock publication export response in biocxml format."""
        return {
            "content": """<?xml version="1.0" encoding="UTF-8"?>
<collection>
  <source>PubTator 3.0</source>
  <date>2024-01-15</date>
  <key>pubtator3.key</key>
  <document>
    <id>29355051</id>
    <infon key="type">journal article</infon>
    <passage>
      <infon key="type">title</infon>
      <offset>0</offset>
      <text>Fraction From Lycium barbarum Polysaccharides Reduces Oxidative Stress</text>
      <annotation id="1">
        <infon key="type">Species</infon>
        <infon key="identifier">112863</infon>
        <location offset="14" length="15"/>
        <text>Lycium barbarum</text>
      </annotation>
    </passage>
    <passage>
      <infon key="type">abstract</infon>
      <offset>72</offset>
      <text>This study investigates the antioxidant properties of polysaccharides extracted from Lycium barbarum.</text>
    </passage>
  </document>
</collection>""",
            "content_type": "application/xml",
        }

    @staticmethod
    def pmc_export_response() -> Dict[str, Any]:
        """Mock PMC publication export response."""
        return {
            "PubTator3": [
                {
                    "_id": "PMC7696669|None",
                    "id": "PMC7696669",
                    "infons": {},
                    "passages": [
                        {
                            "infons": {
                                "journal": "Nature. 2020 Dec;588(7838):498-502.",
                                "year": "2020",
                                "type": "title",
                            },
                            "offset": 0,
                            "text": "Structure-based drug design identifies COVID-19 therapeutics.",
                            "sentences": [],
                            "annotations": [
                                {
                                    "id": "1",
                                    "infons": {
                                        "identifier": "MESH:C000657245",
                                        "type": "Disease",
                                        "valid": True,
                                        "normalized": ["MESH:C000657245"],
                                        "database": "ncbi_mesh",
                                        "normalized_id": "C000657245",
                                        "biotype": "disease",
                                        "name": "COVID-19",
                                        "accession": "@DISEASE_COVID_19",
                                    },
                                    "text": "COVID-19",
                                    "locations": [{"offset": 41, "length": 8}],
                                }
                            ],
                            "relations": [],
                        }
                    ],
                    "relations": [],
                    "pmid": 33087784,
                    "pmcid": "PMC7696669",
                    "meta": {},
                    "date": "2020-12-17T00:00:00Z",
                    "journal": "Nature",
                    "authors": ["Hoffman RL", "Kania RS", "Brothers MA"],
                    "relations_display": [],
                }
            ]
        }

    @staticmethod
    def entity_autocomplete_response() -> List[Dict[str, Any]]:
        """Mock entity autocomplete response."""
        return [
            {
                "_id": "@DISEASE_Neoplasms",
                "biotype": "disease",
                "db_id": "D009369",
                "db": "ncbi_mesh",
                "name": "Neoplasms",
                "match": "Matched on synonyms <m>Cancer</m>",
            },
            {
                "_id": "@DISEASE_Breast_Neoplasms",
                "biotype": "disease",
                "db_id": "D001943",
                "db": "ncbi_mesh",
                "name": "Breast Neoplasms",
                "match": "Matched on synonyms <m>Breast Cancer</m>",
            },
            {
                "_id": "@GENE_BRCA1",
                "biotype": "gene",
                "db_id": "672",
                "db": "ncbi_gene",
                "name": "BRCA1",
                "match": "Matched on symbol <m>BRCA1</m>",
            },
            {
                "_id": "@CHEMICAL_Aspirin",
                "biotype": "chemical",
                "db_id": "D001241",
                "db": "ncbi_mesh",
                "name": "Aspirin",
                "match": "Matched on name <m>Aspirin</m>",
            },
        ]

    @staticmethod
    def search_publications_response() -> Dict[str, Any]:
        """Mock publication search response."""
        return {
            "results": [
                {
                    "_id": "37711410",
                    "pmid": 37711410,
                    "title": "Remdesivir for COVID-19 treatment.",
                    "journal": "Hosp Pharm",
                    "authors": ["Levien TL", "Baker DE"],
                    "date": "2023-10-01T00:00:00Z",
                    "doi": "10.1177/0018578721999804",
                    "score": 266.66373,
                    "text_hl": "@<m>CHEMICAL_remdesivir</m> for @<m>DISEASE_COVID_19</m> treatment.",
                    "abstract": "Comprehensive review of remdesivir efficacy in COVID-19 patients.",
                },
                {
                    "_id": "37061276",
                    "pmid": 37061276,
                    "pmcid": "PMC9910426",
                    "title": "Remdesivir: Mechanism of Action and Clinical Applications",
                    "journal": "Profiles Drug Subst Excip Relat Methodol",
                    "authors": ["Bakheit AH", "Darwish H"],
                    "date": "2023-01-01T00:00:00Z",
                    "score": 265.77936,
                    "text_hl": "@<m>CHEMICAL_remdesivir</m>: Mechanism of Action",
                    "abstract": "Detailed analysis of remdesivir pharmacokinetics and pharmacodynamics.",
                },
                {
                    "_id": "35123456",
                    "pmid": 35123456,
                    "title": "BRCA1 mutations in hereditary breast cancer",
                    "journal": "Cancer Res",
                    "authors": ["Smith J", "Jones M", "Brown K"],
                    "date": "2022-05-15T00:00:00Z",
                    "score": 245.32,
                    "text_hl": "@<m>GENE_BRCA1</m> mutations in hereditary @<m>DISEASE_breast_cancer</m>",
                    "abstract": "Analysis of BRCA1 gene variants and their clinical significance.",
                },
            ],
            "total": 150,
            "per_page": 20,
        }

    @staticmethod
    def entity_relations_response() -> List[Dict[str, Any]]:
        """Mock entity relations response."""
        return [
            {
                "type": "treat",
                "source": "@CHEMICAL_remdesivir",
                "target": "@DISEASE_COVID_19",
                "publications": 2155,
            },
            {
                "type": "treat",
                "source": "@CHEMICAL_remdesivir",
                "target": "@DISEASE_Coronavirus_Infections",
                "publications": 94,
            },
            {
                "type": "cause",
                "source": "@GENE_BRCA1",
                "target": "@DISEASE_Breast_Neoplasms",
                "publications": 8925,
            },
            {
                "type": "interact",
                "source": "@CHEMICAL_warfarin",
                "target": "@CHEMICAL_aspirin",
                "publications": 567,
            },
        ]

    @staticmethod
    def text_annotation_submit_response() -> str:
        """Mock text annotation submit response."""
        return "0DA64A2FE4D635D5820C"

    @staticmethod
    def text_annotation_results_completed() -> Dict[str, Any]:
        """Mock text annotation results response (completed)."""
        return {
            "status": "completed",
            "original_text": "The ESR1 gene mutations are associated with breast cancer risk.",
            "bioconcept": "Gene",
            "annotations": [
                {
                    "start": 4,
                    "end": 8,
                    "text": "ESR1",
                    "entity_id": "@GENE_2099",
                    "entity_type": "Gene",
                    "confidence": 0.95,
                },
                {
                    "start": 47,
                    "end": 60,
                    "text": "breast cancer",
                    "entity_id": "@DISEASE_D001943",
                    "entity_type": "Disease",
                    "confidence": 0.92,
                },
            ],
            "processing_time": 12.5,
        }

    @staticmethod
    def text_annotation_results_processing() -> Dict[str, Any]:
        """Mock text annotation results response (still processing)."""
        return {
            "status": "processing",
            "original_text": "The ESR1 gene mutations are associated with breast cancer risk.",
            "bioconcept": "Gene",
            "annotations": [],
            "message": "Processing in progress. Please try again in a few moments.",
        }

    @staticmethod
    def text_annotation_results_failed() -> Dict[str, Any]:
        """Mock text annotation results response (failed)."""
        return {
            "status": "failed",
            "original_text": "The ESR1 gene mutations are associated with breast cancer risk.",
            "bioconcept": "Gene",
            "error": "Text processing failed due to server error",
            "annotations": [],
        }


class MockErrorResponses:
    """Collection of mock error responses for testing."""

    @staticmethod
    def rate_limit_error() -> Dict[str, Any]:
        """Mock rate limit error response."""
        return {
            "error": "Rate limit exceeded",
            "message": "Too many requests. Please wait 60 seconds before trying again.",
            "status": 429,
            "retry_after": 60,
        }

    @staticmethod
    def not_found_error() -> Dict[str, Any]:
        """Mock not found error response."""
        return {
            "error": "Not found",
            "message": "The requested PMIDs were not found in the database",
            "status": 404,
        }

    @staticmethod
    def validation_error() -> Dict[str, Any]:
        """Mock validation error response."""
        return {
            "error": "Validation error",
            "message": "Invalid request parameters provided",
            "status": 422,
            "details": {
                "pmids": ["Invalid PMID format: 'invalid_pmid'"],
                "format": ["Format 'invalid_format' is not supported"],
            },
        }

    @staticmethod
    def server_error() -> Dict[str, Any]:
        """Mock internal server error response."""
        return {
            "error": "Internal server error",
            "message": "An unexpected error occurred while processing your request",
            "status": 500,
        }

    @staticmethod
    def service_unavailable_error() -> Dict[str, Any]:
        """Mock service unavailable error response."""
        return {
            "error": "Service unavailable",
            "message": "PubTator3 service is temporarily unavailable",
            "status": 503,
        }


class MockCacheResponses:
    """Collection of mock cache-related responses for testing."""

    @staticmethod
    def cache_statistics() -> Dict[str, Any]:
        """Mock cache statistics response."""
        return {
            "total_size": 1500,
            "current_size": 245,
            "hit_rate": 0.847,
            "miss_rate": 0.153,
            "total_hits": 1205,
            "total_misses": 218,
            "detailed_stats": {
                "publication_export": {
                    "size": 89,
                    "hits": 445,
                    "misses": 67,
                    "hit_rate": 0.869,
                },
                "pmc_export": {
                    "size": 45,
                    "hits": 234,
                    "misses": 23,
                    "hit_rate": 0.911,
                },
                "search": {
                    "size": 111,
                    "hits": 526,
                    "misses": 128,
                    "hit_rate": 0.804,
                },
            },
        }

    @staticmethod
    def cache_clear_response() -> Dict[str, Any]:
        """Mock cache clear response."""
        return {
            "success": True,
            "message": "Cache cleared successfully",
            "cleared_items": 245,
            "pattern": None,
        }
