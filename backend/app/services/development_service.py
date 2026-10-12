def suitability(area_sqft: float, property_type: str, location: str) -> list[dict]:
    # This is a planning heuristic only; it is not a zoning/building approval engine.
    options=[]
    for bhk,min_area in [(1,450),(2,700),(3,1000),(4,1400),(5,1800)]:
        options.append({"option":f"{bhk} BHK", "suitable":area_sqft>=min_area, "minimum_area_sqft":min_area})
    options += [
        {"option":"Villa","suitable":area_sqft>=1200,"minimum_area_sqft":1200},
        {"option":"Apartment","suitable":area_sqft>=1000,"minimum_area_sqft":1000},
        {"option":"Independent House","suitable":area_sqft>=700,"minimum_area_sqft":700},
        {"option":"Commercial","suitable":area_sqft>=600,"minimum_area_sqft":600},
    ]
    return options
