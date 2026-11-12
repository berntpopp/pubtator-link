"""Labeled search_literature queries for the offline rerank eval (#182, #243).

Each case: query text, the PMIDs a curator expects on page 1 (discovery / landmark
papers, titles verified against PubTator3 when the fixture was recorded), and a kind.
"""

from __future__ import annotations

CASES: list[dict[str, object]] = [
    # #243: discovery papers the curation study missed on page 1.
    {"query": "TBC1D8B nephrotic syndrome", "relevant": ["31732614"], "kind": "gene"},
    {"query": "KATNIP Joubert syndrome", "relevant": ["26714646"], "kind": "gene"},
    {"query": "ZNF423 nephronophthisis", "relevant": ["22863007"], "kind": "gene"},
    {"query": "DDX59 oral-facial-digital syndrome", "relevant": ["23972372"], "kind": "gene"},
    {"query": "FXYD2 hypomagnesemia", "relevant": ["11062458"], "kind": "gene"},
    {"query": "SYNPO focal segmental glomerulosclerosis", "relevant": ["19666657"], "kind": "gene"},
    {"query": "ADAMTS9 nephronophthisis", "relevant": ["30609407"], "kind": "gene"},
    # Gene-disease discovery papers.
    {"query": "NPHS1 congenital nephrotic syndrome", "relevant": ["9660941"], "kind": "gene"},
    {
        "query": "NPHS2 steroid-resistant nephrotic syndrome",
        "relevant": ["10742096"],
        "kind": "gene",
    },
    {"query": "MECP2 Rett syndrome", "relevant": ["10508514"], "kind": "gene"},
    {"query": "HNF1B MODY renal cysts", "relevant": ["9398836"], "kind": "gene"},
    {"query": "COL4A5 Alport syndrome", "relevant": ["2349482"], "kind": "gene"},
    {"query": "LRRK2 Parkinson disease", "relevant": ["15541309", "15541308"], "kind": "gene"},
    {
        "query": "SCN1A severe myoclonic epilepsy of infancy",
        "relevant": ["11359211"],
        "kind": "gene",
    },
    {"query": "TP53 germline Li-Fraumeni syndrome", "relevant": ["1978757"], "kind": "gene"},
    {"query": "APOL1 kidney disease African Americans", "relevant": ["20647424"], "kind": "gene"},
    # Variant queries.
    {"query": "BRAF V600E human cancer", "relevant": ["12068308"], "kind": "variant"},
    {
        "query": "JAK2 V617F polycythemia vera",
        "relevant": ["15793561", "15781101", "15858187"],
        "kind": "variant",
    },
    {"query": "HFE C282Y hereditary hemochromatosis", "relevant": ["8696333"], "kind": "variant"},
    {
        "query": "factor V Leiden resistance to activated protein C",
        "relevant": ["8164741"],
        "kind": "variant",
    },
    {
        "query": "EGFR mutations gefitinib lung cancer",
        "relevant": ["15118073", "15118125"],
        "kind": "variant",
    },
    # Phenotype / natural-language questions (no gene symbol in the query).
    {
        "query": "which gene is mutated in Marfan syndrome",
        "relevant": ["1852208"],
        "kind": "phenotype",
    },
    {
        "query": "cloning of the gene responsible for cystic fibrosis",
        "relevant": ["2475911", "2570460", "2772657"],
        "kind": "phenotype",
    },
    {
        "query": "Huntington disease trinucleotide repeat gene discovery",
        "relevant": ["8458085"],
        "kind": "phenotype",
    },
    {
        "query": "fragile X syndrome gene with a CGG repeat",
        "relevant": ["1710175"],
        "kind": "phenotype",
    },
    {
        "query": "protein missing in Duchenne muscular dystrophy",
        "relevant": ["3319190"],
        "kind": "phenotype",
    },
    {
        "query": "gene for hereditary hemorrhagic telangiectasia type 1",
        "relevant": ["7894484"],
        "kind": "phenotype",
    },
    {"query": "genetic cause of achondroplasia", "relevant": ["8078586"], "kind": "phenotype"},
    {
        "query": "gene for autosomal dominant polycystic kidney disease on chromosome 16",
        "relevant": ["8004675"],
        "kind": "phenotype",
    },
]
