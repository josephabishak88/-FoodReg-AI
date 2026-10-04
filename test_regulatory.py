from regulatory_database import check_ingredient


TEST_INGREDIENTS = [
    "E211",
    "INS 211",
    "INS211",
    "Sodium Benzoate",
    "Sodium Benzoat",
    "E330",
    "INS 330",
    "E33O",
    "Amaranth",
    "E123",
    "Unknown Ingredient XYZ",
]


print("=" * 70)
print("FoodReg AI - Regulatory Matching Test")
print("=" * 70)


for ingredient in TEST_INGREDIENTS:

    result = check_ingredient(
        ingredient
    )

    print("\nInput:")
    print(f"  {ingredient}")

    print(
        f"Found: {result['found']}"
    )

    print(
        f"Canonical: {result.get('canonical')}"
    )

    print(
        f"Match method: {result.get('match_method')}"
    )

    print(
        f"Confidence: {result.get('match_confidence')}"
    )

    if result["found"]:

        print(
            f"INS: {result.get('ins')}"
        )

        print(
            "Countries:"
        )

        for country, data in result[
            "jurisdictions"
        ].items():

            print(
                f"  {country}: "
                f"{data.get('status')}"
            )

    else:

        print(
            "  ⚪ No reliable regulatory record"
        )


print("\n")
print("=" * 70)
print("Testing complete")
print("=" * 70)