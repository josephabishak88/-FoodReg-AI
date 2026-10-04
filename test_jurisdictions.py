from jurisdiction_registry import (
    print_registry,
    get_supported_jurisdictions,
)


print_registry()

print("\nSupported jurisdictions:")

for jurisdiction in get_supported_jurisdictions():
    print(f" - {jurisdiction}")