"""Test data fixtures and constants for PubTator-Link testing."""


class TestPMIDs:
    """Collection of test PMIDs for various scenarios."""

    # Valid PMIDs for different types of testing
    VALID_SINGLE = "29355051"
    VALID_MULTIPLE = ["29355051", "32511357", "34170578"]
    VALID_LARGE_SET = [str(i) for i in range(30000000, 30000050)]  # 50 PMIDs

    # PMIDs with known content characteristics
    WITH_SPECIES_ANNOTATIONS = "29355051"  # Has Lycium barbarum annotations
    WITH_GENE_ANNOTATIONS = "32511357"  # Has BRCA1 annotations
    WITH_DISEASE_ANNOTATIONS = "34170578"  # Has cancer annotations
    WITH_CHEMICAL_ANNOTATIONS = "37711410"  # Has remdesivir annotations

    # Edge cases
    INVALID_FORMAT = ["abc123", "not_a_pmid", ""]
    NON_EXISTENT = ["99999999", "00000000"]
    MIXED_VALID_INVALID = ["29355051", "invalid_pmid", "32511357"]


class TestPMCIDs:
    """Collection of test PMC IDs for various scenarios."""

    # Valid PMC IDs
    VALID_SINGLE = "PMC7696669"
    VALID_MULTIPLE = ["PMC7696669", "PMC8869656", "PMC9123456"]

    # Invalid PMC IDs
    INVALID_FORMAT = ["PMC_invalid", "123456", "pmc7696669", ""]
    NON_EXISTENT = ["PMC9999999", "PMC0000000"]
    MIXED_VALID_INVALID = ["PMC7696669", "invalid_pmc", "PMC8869656"]


class TestQueries:
    """Collection of test search queries for different scenarios."""

    # Free text queries
    FREE_TEXT_BASIC = "breast cancer"
    FREE_TEXT_COMPLEX = "BRCA1 mutations hereditary breast cancer treatment"
    FREE_TEXT_WITH_SPECIES = "COVID-19 SARS-CoV-2 infection"

    # Entity ID queries
    ENTITY_GENE = "@GENE_BRCA1"
    ENTITY_DISEASE = "@DISEASE_Neoplasms"
    ENTITY_CHEMICAL = "@CHEMICAL_remdesivir"
    ENTITY_SPECIES = "@SPECIES_Homo_sapiens"

    # Boolean queries
    BOOLEAN_AND = "@CHEMICAL_Doxorubicin AND @DISEASE_Neoplasms"
    BOOLEAN_OR = "@GENE_BRCA1 OR @GENE_BRCA2"
    BOOLEAN_NOT = "@DISEASE_COVID_19 NOT @CHEMICAL_hydroxychloroquine"

    # Relation queries
    RELATION_TREAT = "relations:treat|@CHEMICAL_remdesivir|Disease"
    RELATION_CAUSE = "relations:cause|@GENE_BRCA1|Disease"
    RELATION_ANY = "relations:ANY|@CHEMICAL_aspirin|Disease"

    # Edge cases
    EMPTY_QUERY = ""
    VERY_LONG_QUERY = "A" * 1000
    SPECIAL_CHARACTERS = "breast cancer (hereditary) & genetic mutations"
    UNICODE_QUERY = "癌症 breast cancer"


class TestEntityIDs:
    """Collection of test entity IDs for various scenarios."""

    # Valid entity IDs by type
    GENES = ["@GENE_BRCA1", "@GENE_BRCA2", "@GENE_TP53", "@GENE_EGFR", "@GENE_KRAS"]

    DISEASES = [
        "@DISEASE_Neoplasms",
        "@DISEASE_Breast_Neoplasms",
        "@DISEASE_COVID_19",
        "@DISEASE_Diabetes_Mellitus",
        "@DISEASE_Alzheimer_Disease",
    ]

    CHEMICALS = [
        "@CHEMICAL_remdesivir",
        "@CHEMICAL_aspirin",
        "@CHEMICAL_metformin",
        "@CHEMICAL_doxorubicin",
        "@CHEMICAL_warfarin",
    ]

    SPECIES = [
        "@SPECIES_Homo_sapiens",
        "@SPECIES_Mus_musculus",
        "@SPECIES_SARS_CoV_2",
        "@SPECIES_Escherichia_coli",
    ]

    # Invalid entity IDs
    INVALID_FORMAT = [
        "GENE_BRCA1",  # Missing @
        "@INVALID_TYPE_TEST",  # Invalid type
        "@GENE_",  # Missing identifier
        "@",  # Only @
        "",  # Empty
        "not_an_entity",  # Random text
    ]


class TestBioconcepts:
    """Collection of bioconcept types and test data."""

    # Valid bioconcept types
    VALID_TYPES = ["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"]

    # Invalid bioconcept types
    INVALID_TYPES = [
        "InvalidType",
        "gene",  # Wrong case
        "DISEASE",  # Wrong case
        "",  # Empty
        "Protein",  # Not supported
        "Drug",  # Not supported
    ]

    # Test text samples for each bioconcept
    TEXT_SAMPLES = {
        "Gene": "The BRCA1 gene mutations are associated with hereditary breast cancer.",
        "Disease": "COVID-19 is a respiratory disease caused by SARS-CoV-2 infection.",
        "Chemical": "Remdesivir shows efficacy in treating COVID-19 patients.",
        "Species": "SARS-CoV-2 is the virus responsible for the COVID-19 pandemic.",
        "Variant": "The p.Arg273His TP53 mutation is found in many cancer types.",
        "CellLine": "HeLa cells are widely used in cancer research studies.",
    }


class TestExportFormats:
    """Collection of export format test data."""

    # Valid formats for publications
    PUBLICATION_FORMATS = ["biocjson", "biocxml", "pubtator"]

    # Valid formats for PMC
    PMC_FORMATS = ["biocjson", "biocxml"]  # PMC doesn't support pubtator

    # Invalid formats
    INVALID_FORMATS = ["json", "xml", "txt", "csv", "invalid", ""]


class TestRelationTypes:
    """Collection of relation type test data."""

    # Valid relation types
    VALID_TYPES = [
        "treat",
        "cause",
        "cotreat",
        "convert",
        "compare",
        "interact",
        "associate",
        "positive_correlate",
        "negative_correlate",
        "prevent",
        "inhibit",
        "stimulate",
        "drug_interact",
    ]

    # Invalid relation types
    INVALID_TYPES = [
        "invalid_relation",
        "treats",  # Wrong form
        "TREAT",  # Wrong case
        "",  # Empty
        "relationship",  # Not supported
        "connected",  # Not supported
    ]


class TestTextSamples:
    """Collection of text samples for annotation testing."""

    # Short texts (< 100 characters)
    SHORT_TEXTS = [
        "BRCA1 mutations increase breast cancer risk.",
        "Aspirin reduces cardiovascular disease risk.",
        "COVID-19 affects respiratory system function.",
    ]

    # Medium texts (100-500 characters)
    MEDIUM_TEXTS = [
        """The BRCA1 gene, located on chromosome 17, plays a crucial role in DNA repair.
           Mutations in BRCA1 significantly increase the risk of hereditary breast and ovarian
           cancer. Genetic testing for BRCA1 mutations is recommended for high-risk individuals.""",
        """Remdesivir is an antiviral medication developed for treating COVID-19 patients.
           Clinical trials have shown that remdesivir can reduce recovery time in hospitalized
           patients with severe COVID-19 symptoms.""",
    ]

    # Long texts (> 500 characters)
    LONG_TEXTS = [
        """Breast cancer is the second most common cancer in women worldwide, with approximately
           2.3 million new cases diagnosed annually. The disease is characterized by the uncontrolled
           growth of cells in breast tissue. Several risk factors contribute to breast cancer development,
           including age, family history, genetic mutations (particularly in BRCA1 and BRCA2 genes),
           hormonal factors, and lifestyle choices. Early detection through mammography screening and
           clinical breast examinations significantly improves treatment outcomes and survival rates.
           Treatment options include surgery, chemotherapy, radiation therapy, hormone therapy, and
           targeted therapies, depending on the cancer stage and molecular characteristics."""
    ]

    # Edge case texts
    EDGE_CASE_TEXTS = [
        "",  # Empty text
        "A",  # Single character
        "A" * 10000,  # Very long text (10k chars)
        "Text with émojis 🧬 and ünïcödé",  # Unicode characters
        "123 456 789 numbers only",  # Numbers only
        "!@#$%^&*() special chars only",  # Special characters only
        "   \n\t   \r\n   ",  # Whitespace only
    ]


class TestCacheScenarios:
    """Collection of cache testing scenarios."""

    # Cache keys for different operations
    CACHE_KEYS = {
        "publication_export": "pub_export:29355051:biocjson:False",
        "pmc_export": "pmc_export:PMC7696669:biocxml",
        "entity_search": "entity_search:cancer:Disease:10",
        "publication_search": "pub_search:breast cancer:1",
        "relations": "relations:@GENE_BRCA1:treat:Disease",
        "text_annotation": "text_annotation:ABC123DEF456",
    }

    # Cache patterns for selective clearing
    CACHE_PATTERNS = [
        "pub_export:",
        "pmc_export:",
        "entity_search:",
        "pub_search:",
        "relations:",
        "text_annotation:",
    ]


class TestPerformanceData:
    """Collection of performance testing data."""

    # Concurrent request configurations
    LOAD_TEST_CONFIGS = [
        {"users": 5, "requests_per_user": 10, "max_response_time": 2.0},
        {"users": 10, "requests_per_user": 20, "max_response_time": 5.0},
        {"users": 25, "requests_per_user": 50, "max_response_time": 10.0},
    ]

    # Rate limiting test data
    RATE_LIMIT_TESTS = [
        {"requests": 3, "timespan": 1.0, "should_pass": True},  # Within limit
        {"requests": 5, "timespan": 1.0, "should_pass": False},  # Exceeds limit
        {"requests": 10, "timespan": 5.0, "should_pass": True},  # Distributed over time
    ]

    # Large dataset tests
    LARGE_DATASETS = {
        "pmids_100": [str(i) for i in range(30000000, 30000100)],
        "pmids_500": [str(i) for i in range(30000000, 30000500)],
        "queries_batch": [f"query_{i}" for i in range(1, 101)],
    }


class TestErrorScenarios:
    """Collection of error testing scenarios."""

    # HTTP status code scenarios
    ERROR_SCENARIOS = [
        {"status": 400, "type": "validation", "message": "Invalid request parameters"},
        {"status": 404, "type": "not_found", "message": "Resource not found"},
        {"status": 422, "type": "unprocessable", "message": "Validation error"},
        {"status": 429, "type": "rate_limit", "message": "Rate limit exceeded"},
        {"status": 500, "type": "server_error", "message": "Internal server error"},
        {"status": 503, "type": "unavailable", "message": "Service unavailable"},
        {"status": 504, "type": "timeout", "message": "Request timeout"},
    ]

    # Network error scenarios
    NETWORK_ERRORS = [
        "ConnectionError",
        "TimeoutError",
        "HTTPError",
        "RequestException",
    ]


class TestValidationCases:
    """Collection of validation test cases."""

    # Parameter validation tests
    VALIDATION_TESTS = [
        # PMID validation
        {"input": "29355051", "valid": True, "type": "pmid"},
        {"input": "invalid_pmid", "valid": False, "type": "pmid"},
        {"input": "", "valid": False, "type": "pmid"},
        # PMC ID validation
        {"input": "PMC7696669", "valid": True, "type": "pmcid"},
        {"input": "pmc7696669", "valid": False, "type": "pmcid"},
        {"input": "PMC_invalid", "valid": False, "type": "pmcid"},
        # Entity ID validation
        {"input": "@GENE_BRCA1", "valid": True, "type": "entity_id"},
        {"input": "GENE_BRCA1", "valid": False, "type": "entity_id"},
        {"input": "@INVALID_TYPE", "valid": False, "type": "entity_id"},
        # Format validation
        {"input": "biocjson", "valid": True, "type": "format"},
        {"input": "invalid_format", "valid": False, "type": "format"},
        {"input": "", "valid": False, "type": "format"},
    ]


# Test configuration constants
TEST_CONFIG = {
    "default_timeout": 30.0,
    "max_retries": 3,
    "rate_limit_per_second": 3,
    "cache_ttl_seconds": 300,
    "max_text_length": 10000,
    "max_pmids_per_request": 100,
    "supported_formats": ["biocjson", "biocxml", "pubtator"],
    "supported_bioconcepts": [
        "Gene",
        "Disease",
        "Chemical",
        "Species",
        "Variant",
        "CellLine",
    ],
}
