"""Comprehensive endpoint tests using documentation examples."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from pubtator_link.server_manager import UnifiedServerManager
from pubtator_link.api.client import PubTator3Client


# Mock responses based on actual API responses
MOCK_PUBLICATION_EXPORT_RESPONSE = {
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
                    },
                    "offset": 0,
                    "text": "Fraction From Lycium barbarum Polysaccharides.",
                    "sentences": [],
                    "annotations": [
                        {
                            "id": "5",
                            "infons": {
                                "identifier": "112863",
                                "type": "Species",
                                "valid": True,
                            },
                            "text": "Lycium barbarum",
                            "locations": [{"offset": 14, "length": 15}],
                        }
                    ],
                    "relations": [],
                }
            ],
            "relations": [],
            "pmid": 29355051,
            "pmcid": None,
            "meta": {},
            "date": "2018-09-01T00:00:00Z",
            "journal": "Integr Cancer Ther",
            "authors": ["Deng X", "Luo S"],
            "relations_display": [],
        }
    ]
}

MOCK_ENTITY_AUTOCOMPLETE_RESPONSE = [
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
        "match": "Matched on synonyms <m>Cancer, Mammary</m>",
    },
]

MOCK_SEARCH_RESPONSE = {
    "results": [
        {
            "_id": "37711410",
            "pmid": 37711410,
            "title": "Remdesivir.",
            "journal": "Hosp Pharm",
            "authors": ["Levien TL", "Baker DE"],
            "date": "2023-10-01T00:00:00Z",
            "doi": "10.1177/0018578721999804",
            "score": 266.66373,
            "text_hl": "@<m>CHEMICAL_remdesivir</m> @CHEMICAL_MESH:C000606551 @@@Remdesivir@@@.",
        },
        {
            "_id": "37061276",
            "pmid": 37061276,
            "pmcid": "PMC9910426",
            "title": "Remdesivir",
            "journal": "Profiles Drug Subst Excip Relat Methodol",
            "authors": ["Bakheit AH", "Darwish H"],
            "date": "2023-01-01T00:00:00Z",
            "score": 265.77936,
            "text_hl": "@<m>CHEMICAL_remdesivir</m> @CHEMICAL_MESH:C000606551 @@@Remdesivir@@@",
        },
    ],
    "total": 150,
    "per_page": 20,
}

MOCK_RELATIONS_RESPONSE = [
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
]

MOCK_TEXT_ANNOTATION_SUBMIT_RESPONSE = "0DA64A2FE4D635D5820C"

MOCK_TEXT_ANNOTATION_RESULTS_RESPONSE = {
    "status": "completed",
    "original_text": "The ESR1 gene mutations and breast cancer risk.",
    "bioconcept": "Gene",
    "annotations": [
        {
            "start": 4,
            "end": 8,
            "text": "ESR1",
            "entity_id": "@GENE_2099",
            "entity_type": "Gene",
            "confidence": 0.95
        }
    ],
    "processing_time": 12.5
}


@pytest.fixture
def test_client():
    """Create test client."""
    manager = UnifiedServerManager()
    app = manager.create_app()
    return TestClient(app)


class TestPublicationRoutes:
    """Test publication export endpoints."""

    @patch.object(PubTator3Client, "export_publications")
    def test_export_publications_biocjson(self, mock_export, test_client):
        """Test publication export in biocjson format."""
        mock_export.return_value = MOCK_PUBLICATION_EXPORT_RESPONSE

        response = test_client.get(
            "/api/publications/export/biocjson",
            params={"pmids": "29355051", "full": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "biocjson"
        assert data["pmids"] == ["29355051"]
        assert data["full_text"] is False
        assert data["count"] == 1

    @patch.object(PubTator3Client, "export_publications")
    def test_export_publications_pubtator(self, mock_export, test_client):
        """Test publication export in pubtator format."""
        mock_export.return_value = {
            "content": (
                "29355051|t|BRCA1 mutations and breast cancer risk\n"
                "29355051|a|Abstract text here\n"
                "32511357|t|Second article title\n"
                "32511357|a|Second abstract"
            )
        }

        response = test_client.get(
            "/api/publications/export/pubtator", params={"pmids": "29355051,32511357"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "pubtator"
        assert data["pmids"] == ["29355051", "32511357"]
        # 2 PMIDs x 2 sections (title + abstract) = 4 documents
        assert data["count"] == 4

    def test_export_publications_invalid_format(self, test_client):
        """Test publication export with invalid format."""
        response = test_client.get(
            "/api/publications/export/invalid", params={"pmids": "29355051"}
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid format" in data["detail"]

    def test_export_publications_full_text_pubtator_error(self, test_client):
        """Test that full text is not allowed with pubtator format."""
        response = test_client.get(
            "/api/publications/export/pubtator",
            params={"pmids": "29355051", "full": True},
        )

        assert response.status_code == 400
        data = response.json()
        assert "Full text is not supported for pubtator format" in data["detail"]

    @patch.object(PubTator3Client, "export_pmc_publications")
    def test_export_pmc_publications(self, mock_export, test_client):
        """Test PMC publication export."""
        mock_export.return_value = MOCK_PUBLICATION_EXPORT_RESPONSE

        response = test_client.get(
            "/api/publications/pmc_export/biocxml",
            params={"pmcids": "PMC7696669,PMC8869656"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "biocxml"
        assert data["pmcids"] == ["PMC7696669", "PMC8869656"]
        assert data["full_text"] is True  # PMC always includes full text
        assert data["count"] == 2

    def test_export_pmc_publications_invalid_format(self, test_client):
        """Test PMC export with unsupported format."""
        response = test_client.get(
            "/api/publications/pmc_export/pubtator", params={"pmcids": "PMC7696669"}
        )

        assert response.status_code == 400
        data = response.json()
        assert "PMC export only supports" in data["detail"]


class TestEntityRoutes:
    """Test entity autocomplete endpoints."""

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_basic(self, mock_autocomplete, test_client):
        """Test basic entity ID search."""
        mock_autocomplete.return_value = MOCK_ENTITY_AUTOCOMPLETE_RESPONSE

        response = test_client.get(
            "/api/entities/autocomplete", params={"query": "cancer", "limit": 10}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["query"] == "cancer"
        assert len(data["matches"]) == 2
        assert data["matches"][0]["identifier"] == "@DISEASE_Neoplasms"
        assert data["matches"][0]["name"] == "Neoplasms"
        assert data["matches"][0]["type"] == "disease"

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_with_concept_filter(
        self, mock_autocomplete, test_client
    ):
        """Test entity search with concept type filter."""
        mock_autocomplete.return_value = MOCK_ENTITY_AUTOCOMPLETE_RESPONSE

        response = test_client.get(
            "/api/entities/autocomplete",
            params={"query": "cancer", "concept": "Disease", "limit": 5},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["concept_filter"] == "Disease"
        assert data["total_matches"] == 2

    def test_search_entity_ids_invalid_concept(self, test_client):
        """Test entity search with invalid concept type."""
        response = test_client.get(
            "/api/entities/autocomplete",
            params={"query": "cancer", "concept": "InvalidType"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid bioconcept" in data["detail"]


class TestSearchRoutes:
    """Test publication search endpoints."""

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_free_text(self, mock_search, test_client):
        """Test free text publication search."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/", params={"text": "breast cancer treatment", "page": 1}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["query"] == "breast cancer treatment"
        assert len(data["results"]) == 2
        assert data["total_results"] == 150
        assert data["page"] == 1
        assert data["per_page"] == 20
        assert data["total_pages"] == 8  # ceil(150/20)

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_entity_id(self, mock_search, test_client):
        """Test entity ID publication search."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/", params={"text": "@CHEMICAL_remdesivir", "page": 1}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "@CHEMICAL_remdesivir"
        assert "37711410" in str(data["results"][0]["pmid"])

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_boolean_query(self, mock_search, test_client):
        """Test boolean search query."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/",
            params={"text": "@CHEMICAL_Doxorubicin AND @DISEASE_Neoplasms", "page": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert "AND" in data["query"]

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_relation_query(self, mock_search, test_client):
        """Test relation search query."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/",
            params={"text": "relations:treat|@CHEMICAL_remdesivir|Disease", "page": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert "relations:treat" in data["query"]

    def test_search_publications_invalid_page(self, test_client):
        """Test search with invalid page number."""
        response = test_client.get("/api/search/", params={"text": "cancer", "page": 0})

        assert response.status_code == 422  # Pydantic validation error

    def test_search_publications_empty_query(self, test_client):
        """Test search with empty query."""
        response = test_client.get("/api/search/", params={"text": "", "page": 1})

        assert response.status_code == 422  # Pydantic validation error


class TestRelationsRoutes:
    """Test entity relations endpoints."""

    @patch.object(PubTator3Client, "find_relations")
    def test_find_related_entities_basic(self, mock_relations, test_client):
        """Test basic entity relations search."""
        mock_relations.return_value = MOCK_RELATIONS_RESPONSE

        response = test_client.get(
            "/api/relations/", params={"e1": "@CHEMICAL_remdesivir"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["primary_entity"] == "@CHEMICAL_remdesivir"
        assert len(data["related_entities"]) == 2
        assert data["total_relations"] == 2

    @patch.object(PubTator3Client, "find_relations")
    def test_find_related_entities_with_type_filter(self, mock_relations, test_client):
        """Test relations search with relation type filter."""
        mock_relations.return_value = MOCK_RELATIONS_RESPONSE

        response = test_client.get(
            "/api/relations/", params={"e1": "@CHEMICAL_remdesivir", "type": "treat"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["relation_filter"] == "treat"
        assert all(rel["relation_type"] == "treat" for rel in data["related_entities"])

    @patch.object(PubTator3Client, "find_relations")
    def test_find_related_entities_with_entity_filter(
        self, mock_relations, test_client
    ):
        """Test relations search with target entity type filter."""
        mock_relations.return_value = MOCK_RELATIONS_RESPONSE

        response = test_client.get(
            "/api/relations/", params={"e1": "@CHEMICAL_remdesivir", "e2": "Disease"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["entity_filter"] == "Disease"

    def test_find_related_entities_invalid_entity_id(self, test_client):
        """Test relations search with invalid entity ID format."""
        response = test_client.get(
            "/api/relations/", params={"e1": "invalid_entity_id"}
        )

        assert response.status_code == 400
        data = response.json()
        assert "Entity ID must start with '@'" in data["detail"]

    def test_find_related_entities_invalid_relation_type(self, test_client):
        """Test relations search with invalid relation type."""
        response = test_client.get(
            "/api/relations/",
            params={"e1": "@CHEMICAL_remdesivir", "type": "invalid_type"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid relation type" in data["detail"]

    def test_find_related_entities_invalid_entity_type(self, test_client):
        """Test relations search with invalid target entity type."""
        response = test_client.get(
            "/api/relations/",
            params={"e1": "@CHEMICAL_remdesivir", "e2": "InvalidType"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid entity type" in data["detail"]


class TestAnnotationRoutes:
    """Test text annotation endpoints."""

    @patch.object(PubTator3Client, "submit_text_annotation")
    def test_submit_text_annotation_basic(self, mock_submit, test_client):
        """Test basic text annotation submission."""
        mock_submit.return_value = MOCK_TEXT_ANNOTATION_SUBMIT_RESPONSE

        response = test_client.post(
            "/api/annotations/submit",
            params={
                "text": "The ESR1 gene mutations and breast cancer risk.",
                "bioconcepts": "Gene,Disease",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "session_id" in data
        assert data["status"] == "submitted"
        assert "Gene" in data["bioconcepts"]
        assert "Disease" in data["bioconcepts"]

    @patch.object(PubTator3Client, "submit_text_annotation")
    def test_submit_text_annotation_all_concepts(self, mock_submit, test_client):
        """Test text annotation with all bioconcepts."""
        mock_submit.return_value = MOCK_TEXT_ANNOTATION_SUBMIT_RESPONSE

        response = test_client.post(
            "/api/annotations/submit",
            params={"text": "Test text", "bioconcepts": "all"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["bioconcepts"]) > 1  # Should include all concept types

    def test_submit_text_annotation_invalid_bioconcept(self, test_client):
        """Test text annotation with invalid bioconcept."""
        response = test_client.post(
            "/api/annotations/submit",
            params={"text": "Test text", "bioconcepts": "InvalidConcept"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid bioconcept" in data["detail"]

    @patch.object(PubTator3Client, "retrieve_text_annotation")
    def test_get_annotation_results(self, mock_get_results, test_client):
        """Test retrieving annotation results."""
        mock_get_results.return_value = MOCK_TEXT_ANNOTATION_RESULTS_RESPONSE

        response = test_client.get(
            "/api/annotations/results/0DA64A2FE4D635D5820C"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["session_id"] == "0DA64A2FE4D635D5820C"
        assert data["status"] == "completed"


class TestCacheRoutes:
    """Test cache management endpoints."""

    def test_get_cache_statistics_basic(self, test_client):
        """Test basic cache statistics retrieval."""
        response = test_client.get("/api/cache/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "stats" in data
        assert "total_size" in data["stats"]
        assert "hit_rate" in data["stats"]

    def test_get_cache_statistics_detailed(self, test_client):
        """Test detailed cache statistics retrieval."""
        response = test_client.get("/api/cache/stats", params={"detailed": True})

        assert response.status_code == 200
        data = response.json()
        assert "detailed_stats" in data

    def test_clear_cache_all(self, test_client):
        """Test clearing all cache."""
        response = test_client.delete("/api/cache/clear")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "cleared_items" in data
        assert data["pattern"] is None

    def test_clear_cache_with_pattern(self, test_client):
        """Test clearing cache with pattern."""
        response = test_client.delete(
            "/api/cache/clear", params={"pattern": "pub_export:"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["pattern"] == "pub_export:"

    def test_clear_cache_empty_pattern(self, test_client):
        """Test clearing cache with empty pattern."""
        response = test_client.delete("/api/cache/clear", params={"pattern": ""})

        assert response.status_code == 400
        data = response.json()
        assert "Cache pattern cannot be empty" in data["detail"]


class TestHealthAndRoot:
    """Test health and root endpoints."""

    def test_root_endpoint(self, test_client):
        """Test root endpoint."""
        response = test_client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "PubTator-Link"
        assert data["version"] == "1.0.0"
        assert "description" in data

    def test_health_endpoint(self, test_client):
        """Test health check endpoint."""
        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
