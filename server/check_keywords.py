from llm.intent_classifier import _BUILDING_KEYWORDS, _SEARCH_KEYWORDS

overlap = _BUILDING_KEYWORDS & _SEARCH_KEYWORDS
print("Overlap:", sorted(overlap))

print("\nSearch keywords that contain a building keyword as substring:")
for sk in sorted(_SEARCH_KEYWORDS):
    building_hits = [bk for bk in _BUILDING_KEYWORDS if bk in sk]
    if building_hits:
        print(f'  search "{sk}" contains building: {building_hits}')

print("\nBuilding keywords that contain a search keyword as substring:")
for bk in sorted(_BUILDING_KEYWORDS):
    search_hits = [sk for sk in _SEARCH_KEYWORDS if sk in bk]
    if search_hits:
        print(f'  building "{bk}" contains search: {search_hits}')

# Also check: for each search keyword used alone as text, what happens?
print("\nSearch-only keywords (not in building set, no building substring):")
pure_search = []
for sk in sorted(_SEARCH_KEYWORDS):
    building_hits = [bk for bk in _BUILDING_KEYWORDS if bk in sk]
    if not building_hits and sk not in _BUILDING_KEYWORDS:
        pure_search.append(sk)
print(f"  Count: {len(pure_search)}")
print(f"  Sample: {pure_search[:10]}")

print("\nBuilding-only keywords (not in search set, no search substring):")
pure_building = []
for bk in sorted(_BUILDING_KEYWORDS):
    search_hits = [sk for sk in _SEARCH_KEYWORDS if sk in bk]
    if not search_hits and bk not in _SEARCH_KEYWORDS:
        pure_building.append(bk)
print(f"  Count: {len(pure_building)}")
print(f"  Sample: {pure_building[:10]}")
