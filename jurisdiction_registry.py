# =========================================================
# FOODREG AI
# GLOBAL JURISDICTION REGISTRY
# =========================================================
#
# This file does NOT contain the actual regulatory decisions.
#
# It tells the application:
#   1. Which jurisdictions we support
#   2. Which official authority owns the data
#   3. Where the official regulatory source is
#   4. What type of source it is
#
# Later, individual data collectors/importers will populate
# the main regulatory database from these sources.
# =========================================================


JURISDICTIONS = {

    # =====================================================
    # INDIA
    # =====================================================

    "India": {

        "code": "IN",

        "type": "country",

        "authority": (
            "Food Safety and Standards Authority "
            "of India (FSSAI)"
        ),

        "source_type": (
            "Regulations and Gazette amendments"
        ),

        "official_source": (
            "https://fssai.gov.in/food-law/regulations/"
        ),

        "additive_source": (
            "https://fssai.gov.in/food-law/regulations/"
            "compendium/food-products-standards"
        ),

        "data_status": "PLANNED",

        "priority": 1,

        "notes": (
            "Use FSSAI regulations, amendments and "
            "original notifications where applicable."
        ),
    },


    # =====================================================
    # UNITED STATES
    # =====================================================

    "United States": {

        "code": "US",

        "type": "country",

        "authority": (
            "U.S. Food and Drug Administration (FDA)"
        ),

        "source_type": (
            "Food ingredient and additive databases"
        ),

        "official_source": (
            "https://www.fda.gov/food"
        ),

        "additive_source": (
            "https://www.fda.gov/food/"
            "food-additives-petitions/"
            "food-additive-status-list"
        ),

        "data_status": "PLANNED",

        "priority": 2,

        "notes": (
            "Regulatory status must be interpreted "
            "using the applicable FDA framework."
        ),
    },


    # =====================================================
    # GREAT BRITAIN
    # =====================================================

    "Great Britain": {

        "code": "GB",

        "type": "jurisdiction",

        "authority": (
            "Food Standards Agency (FSA)"
        ),

        "source_type": (
            "Regulated Products Register"
        ),

        "official_source": (
            "https://data.food.gov.uk/"
            "regulated-products/"
        ),

        "additive_source": (
            "https://data.food.gov.uk/"
            "regulated-products/"
            "food_authorisations/"
        ),

        "data_status": "PLANNED",

        "priority": 3,

        "notes": (
            "The register contains authorised food "
            "additives and conditions of use."
        ),
    },


    # =====================================================
    # EUROPEAN UNION
    # =====================================================

    "European Union": {

        "code": "EU",

        "type": "supranational_jurisdiction",

        "authority": (
            "European Commission"
        ),

        "source_type": (
            "Union List / Additives Database"
        ),

        "official_source": (
            "https://food.ec.europa.eu/"
            "food-safety/food-improvement-agents/"
            "additives/database_en"
        ),

        "additive_source": (
            "https://food.ec.europa.eu/"
            "food-safety/food-improvement-agents/"
            "additives/database_en"
        ),

        "data_status": "PLANNED",

        "priority": 4,

        "notes": (
            "The EU database is based on the Union "
            "List of food additives and conditions of use."
        ),
    },


    # =====================================================
    # CANADA
    # =====================================================

    "Canada": {

        "code": "CA",

        "type": "country",

        "authority": (
            "Health Canada"
        ),

        "source_type": (
            "Lists of Permitted Food Additives"
        ),

        "official_source": (
            "https://www.canada.ca/en/health-canada/"
            "services/food-nutrition/food-safety/"
            "food-additives/lists-permitted.html"
        ),

        "additive_source": (
            "https://www.canada.ca/en/health-canada/"
            "services/food-nutrition/food-safety/"
            "food-additives/lists-permitted.html"
        ),

        "data_status": "PLANNED",

        "priority": 5,

        "notes": (
            "Lists include permitted foods, purposes "
            "of use and maximum levels/conditions."
        ),
    },


    # =====================================================
    # AUSTRALIA
    # =====================================================

    "Australia": {

        "code": "AU",

        "type": "country",

        "authority": (
            "Food Standards Australia New Zealand (FSANZ)"
        ),

        "source_type": (
            "Australia New Zealand Food Standards Code"
        ),

        "official_source": (
            "https://www.foodstandards.gov.au/"
            "food-standards-code/legislation"
        ),

        "additive_source": (
            "https://www.foodstandards.gov.au/"
            "food-standards-code/legislation"
        ),

        "data_status": "PLANNED",

        "priority": 6,

        "notes": (
            "The authoritative current Code is linked "
            "through the Federal Register of Legislation."
        ),
    },


    # =====================================================
    # NEW ZEALAND
    # =====================================================

    "New Zealand": {

        "code": "NZ",

        "type": "country",

        "authority": (
            "Food Standards Australia New Zealand (FSANZ)"
        ),

        "source_type": (
            "Australia New Zealand Food Standards Code"
        ),

        "official_source": (
            "https://www.foodstandards.gov.au/"
        ),

        "additive_source": (
            "https://www.foodstandards.gov.au/"
            "food-standards-code/legislation"
        ),

        "data_status": "PLANNED",

        "priority": 7,

        "notes": (
            "FSANZ develops and administers the "
            "Australia New Zealand Food Standards Code."
        ),
    },


    # =====================================================
    # SINGAPORE
    # =====================================================

    "Singapore": {

        "code": "SG",

        "type": "country",

        "authority": (
            "Singapore Food Agency (SFA)"
        ),

        "source_type": (
            "Food Additives Search / Food Regulations"
        ),

        "official_source": (
            "https://www.sfa.gov.sg/"
        ),

        "additive_source": (
            "https://www.sfa.gov.sg/tools-and-resources/"
            "food-additives-search"
        ),

        "data_status": "PLANNED",

        "priority": 8,

        "notes": (
            "The SFA search allows lookup by INS number "
            "or additive name."
        ),
    },


    # =====================================================
    # JAPAN
    # =====================================================

    "Japan": {

        "code": "JP",

        "type": "country",

        "authority": (
            "Ministry of Health, Labour and Welfare (MHLW)"
        ),

        "source_type": (
            "Food additive regulatory framework"
        ),

        "official_source": (
            "https://www.mhlw.go.jp/stf/"
            "seisakunitsuite/bunya/kenkou_iryou/"
            "shokuhin/syokuten/index_00012.html"
        ),

        "additive_source": (
            "https://www.mhlw.go.jp/stf/"
            "seisakunitsuite/bunya/kenkou_iryou/"
            "shokuhin/syokuten/index_00012.html"
        ),

        "data_status": "PLANNED",

        "priority": 9,

        "notes": (
            "Japan uses a positive-list approach for "
            "food additives and specifies standards "
            "and conditions for authorised additives."
        ),
    },


    # =====================================================
    # CODEX - GLOBAL REFERENCE
    # =====================================================

    "Codex":

        {

        "code": "CODEX",

        "type": "international_reference",

        "authority": (
            "Codex Alimentarius Commission"
        ),

        "source_type": (
            "General Standard for Food Additives (GSFA)"
        ),

        "official_source": (
            "https://codex.fao.org/"
            "codex-texts/codex-online-databases/gsfa"
        ),

        "additive_source": (
            "https://codex.fao.org/"
            "codex-texts/codex-online-databases/gsfa"
        ),

        "data_status": "REFERENCE",

        "priority": 0,

        "notes": (
            "Global reference layer. Codex information "
            "must not be presented as national law."
        ),
    },
}


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def get_jurisdiction(
    name: str
):

    return JURISDICTIONS.get(
        name
    )


def get_supported_jurisdictions():

    return [
        name
        for name, data in JURISDICTIONS.items()
        if data.get("data_status")
        in {
            "PLANNED",
            "ACTIVE",
            "REFERENCE",
        }
    ]


def get_country_jurisdictions():

    return {
        name: data
        for name, data in JURISDICTIONS.items()
        if data.get("type") == "country"
    }


def get_active_jurisdictions():

    return {
        name: data
        for name, data in JURISDICTIONS.items()
        if data.get("data_status") == "ACTIVE"
    }


def get_official_source(
    jurisdiction: str
):

    data = JURISDICTIONS.get(
        jurisdiction
    )

    if not data:
        return None

    return data.get(
        "official_source"
    )


def print_registry():

    print("=" * 70)
    print("FoodReg AI - Global Jurisdiction Registry")
    print("=" * 70)

    for name, data in JURISDICTIONS.items():

        print(
            f"{data['code']:8} "
            f"{name:25} "
            f"{data['data_status']:10} "
            f"{data['authority']}"
        )

    print("=" * 70)