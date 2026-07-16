import numpy as np
import polars as pl

FIRST_NAMES = np.array(
    [
        "Alice",
        "Amélie",
        "André",
        "Anna",
        "Antoine",
        "Camille",
        "Carlos",
        "Chloé",
        "Claire",
        "Daniel",
        "David",
        "Élodie",
        "Emma",
        "Eva",
        "François",
        "Giulia",
        "Hélène",
        "Hugo",
        "Inès",
        "Isabel",
        "Jan",
        "Javier",
        "Julia",
        "Julien",
        "Karl",
        "Laura",
        "Léa",
        "Louis",
        "Luca",
        "Lucas",
        "Manon",
        "Marco",
        "Maria",
        "Marie",
        "Martin",
        "Noah",
        "Paul",
        "Pierre",
        "Sofia",
        "Thomas",
    ]
)
LAST_NAMES = np.array(
    [
        "Bernard",
        "Bianchi",
        "Blanc",
        "Bonnet",
        "Costa",
        "Dubois",
        "Dupont",
        "Durand",
        "Fernández",
        "Ferrari",
        "Fischer",
        "Fontaine",
        "Garcia",
        "Girard",
        "Hoffmann",
        "Jansen",
        "Klein",
        "Lambert",
        "Laurent",
        "Lefèvre",
        "Leroy",
        "Martínez",
        "Meyer",
        "Moreau",
        "Müller",
        "Peeters",
        "Petit",
        "Richard",
        "Ricci",
        "Robert",
        "Rossi",
        "Roux",
        "Schmidt",
        "Schneider",
        "Silva",
        "Simon",
        "Vincent",
        "Weber",
        "Wouters",
        "Zimmermann",
    ]
)
STEMS = np.array(
    [
        "Alder",
        "Altis",
        "Arden",
        "Aster",
        "Atlas",
        "Aurora",
        "Boreal",
        "Cedar",
        "Cobalt",
        "Corvus",
        "Delta",
        "Equinox",
        "Fjord",
        "Helios",
        "Horizon",
        "Iris",
        "Juniper",
        "Lumen",
        "Meridian",
        "Nimbus",
        "Nova",
        "Onyx",
        "Orion",
        "Pinnacle",
        "Quartz",
        "Riviera",
        "Sable",
        "Sequoia",
        "Solaris",
        "Summit",
    ]
)
SECTORS = np.array(
    [
        "Logistics",
        "Foods",
        "Energy",
        "Systems",
        "Pharma",
        "Textiles",
        "Motors",
        "Chemicals",
        "Industries",
        "Holdings",
        "Construction",
        "Retail",
        "Media",
        "Software",
        "Metals",
        "Packaging",
        "Shipping",
        "Hotels",
        "Farms",
        "Engineering",
    ]
)
LEGAL_FORMS = np.array(["SA", "SAS", "SARL", "GmbH", "AG", "SpA", "Srl", "BV", "NV", "SL", "Ltd", "plc", "Inc"])
VOCABULARIES = {"first": FIRST_NAMES, "last": LAST_NAMES, "stem": STEMS, "sector": SECTORS, "form": LEGAL_FORMS}


def names(rng: np.random.Generator, segments: np.ndarray, country_labels: np.ndarray) -> pl.Series:
    size = segments.shape[0]
    words = {
        name: vocabulary[rng.integers(vocabulary.shape[0], size=size)] for name, vocabulary in VOCABULARIES.items()
    }
    parts = pl.DataFrame(
        {"segment": segments, "label": country_labels, **words},
        schema=dict.fromkeys(("segment", "label", *VOCABULARIES), pl.Utf8),
    )
    return parts.select(
        pl.when(pl.col("segment") == "RETAIL")
        .then(pl.concat_str("first", "last", separator=" "))
        .when(pl.col("segment") == "SOVEREIGN")
        .then(pl.concat_str(pl.lit("Government of"), "label", separator=" "))
        .when(pl.col("segment") == "BANK")
        .then(pl.concat_str("stem", pl.lit("Bank"), "form", separator=" "))
        .otherwise(pl.concat_str("stem", "sector", "form", separator=" "))
        .alias("cpty_name")
    ).to_series()
