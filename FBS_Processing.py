#---------------------------- Imports -----------------------------#
import pandas as pd
import os 
from sesame.sesametoolbox import add_iso3_column
#---------------------------- Configuration -----------------------------#
""" Edit these to change which years are kept for each dataset"""
FILE_YEAR_RANGE = {
    "FBS_Raw_1961-2013.csv": (2000, 2009),
    "FBS_Raw_2010-2023.csv": (2010, 2020),
}

"Edit to change the columns to keep"
Cols_to_remove = ["Element Code", "Item Code", "Item Code (FBS)", "Area Code", "Area Code (M49)"]

Country_groupings_to_remove = [
    # Regional aggregates & groupings
    "Australia and New Zealand", "Asia", "Africa", "Americas", "Central America", "Central Asia",
    "Caribbean","China", "Eastern Africa", "Eastern Asia", "Eastern Europe", "Europe",
    "European Union (27)", "Land Locked Developing Countries", "Land Locked Developing Countries (LLDCs)",
    "Least Developed Countries", "Least Developed Countries (LDCs)", "Low Income Food Deficit Countries",
    "Low Income Food Deficit Countries (LIFDCs)", "Middle Africa", "Net Food Importing Developing Countries",
    "Net Food Importing Developing Countries (NFIDCs)", "Northern Africa", "Northern America",
    "Northern Europe", "Oceania", "Polynesia", "Melanesia", "Micronesia", "South America",
    "South-eastern Asia", "Southern Africa", "Southern Asia", "Southern Europe",
    "Western Africa", "Western Asia", "Western Europe", "World","Small Island Developing States","Small Island Developing States (SIDS)",

    # Historical/dissolved entities
    "Belgium-Luxembourg", "Czechoslovakia", "Ethiopia PDR", "Netherlands Antilles (former)",
    "Serbia and Montenegro", "Sudan (former)", "USSR", "Yugoslav SFR",

    # Only in old release (missing from 2010–2020)
    "Benin", "Bermuda", "Brunei Darussalam", "Central African Republic", "Chad",
    "Dominica", "Japan", "Mali", "Sudan", "Togo",

    # Only in new release (missing from 2000–2009)
    "Bahrain", "Bhutan", "Comoros", "Democratic Republic of the Congo", "Libya", "Marshall Islands",
    "Micronesia (Federated States of)", "Nauru", "Papua New Guinea", "Qatar",
    "Seychelles", "Syrian Arab Republic", "Tonga", "Tuvalu",
]

Item_fix = {
    "Rice (Milled Equivalent)": "Rice and products",

    "Groundnuts (Shelled Eq)": "Groundnuts",

    "Cereals, Other": "Cereals, other"
}			

METHODOLOGY_CONVERSIONS = {
    "Rice (Milled Equivalent)": 1 / 0.67,   # milled -> paddy (~1.4925)
    "Groundnuts (Shelled Eq)":  1 / 0.70,   # shelled -> in-shell (~1.4286)
}


# ----------------- Helper functions -------- #
def is_year_col(c) -> bool:
    """Returns True if a column name looks like a 4-digit year (e.g. '2010')."""
    s = str(c)
    return len(s) == 4 and s.isdigit()

def filter_years(df: pd.DataFrame, start_year: int, end_year: int) -> pd.DataFrame:
    """
    Drops any column that looks like a year (4-digit string) and falls outside [start_year, end_year].
    Non-year columns are always kept.
    In the case of FBS, you must remove the Y prefix for all year columns before calling either of the helpers
    """
    cols_to_keep = []
    for col in df.columns:
        if is_year_col(col):
            if start_year <= int(col) <= end_year:
                cols_to_keep.append(col)
        else:
            cols_to_keep.append(col)
    return df[cols_to_keep]


def apply_methodology_conversion(df: pd.DataFrame) -> pd.DataFrame:
    """
    Scale pre-2010 FBS items reported in milled/shelled equivalent into
    the post-2010 paddy/in-shell basis, so the time series is continuous
    across the 2009/2010 methodology break.

    MUST be called BEFORE Item_fix renames are applied.
    """
    if "Item" not in df.columns:
        return df

    year_cols = [c for c in df.columns if is_year_col(c)]
    if not year_cols:
        return df

    for old_item, factor in METHODOLOGY_CONVERSIONS.items():
        mask = df["Item"] == old_item
        if mask.any():
            df.loc[mask, year_cols] = df.loc[mask, year_cols] * factor
            print(f"Converted {mask.sum()} rows of '{old_item}' "
                  f"by {factor:.4f} (old -> new methodology)")

    return df


def load_single_fbs_file(filepath: str) -> pd.DataFrame:
    """
    Loads one FBS CSV, drops unneeded metadata columns, renames columns,
    strips the 'Y' prefix from year columns, and keeps only Production rows.
    Does NOT filter years — call filter_years() after.

    Parameters
        filepath: str  --> full path to a FBS csv file 

    Returns: 
        Pd.dataframe --> Cleaned single file dataframe  with standardized column names
    """
    
    try:
        df = pd.read_csv(filepath, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(filepath, encoding="latin-1")


    # Drop unnecessary metadata columns (only if present)
    df = df.drop(columns=[col for col in Cols_to_remove if col in df.columns])

    # Strip 'Y' prefix from year columns (e.g. Y2005 -> 2005)
    year_col_map = {col: col[1:] for col in df.columns if col.startswith("Y") and col[1:].isdigit()}
    df = df.rename(columns=year_col_map)

    # Keep only Production rows
    if "Element" in df.columns:
        df = df[df["Element"] == "Production"].copy()

    # Standardize country column name
    df = df.rename(columns={"Area": "Country"})

    # Remove aggregate/regional entries that aren't individual countries
    if "Country" in df.columns:    
        df = df[~df["Country"].isin(Country_groupings_to_remove)]

    #Apply conversion factors
    df = apply_methodology_conversion(df)


    #Standardized names 
    if "Item" in df.columns:
        df["Item"] = df["Item"].replace(Item_fix)


    return df

#-------------------------------------- Main Function where cleaned(final) CSV is created ----------------#
def load_and_merge_fbs(path_to_fbs: str) -> pd.DataFrame:
    """
    Loads all FBS CSVs from a directory, cleans each one, filters to
    the configured year range, and merges pre-2010 / post-2010 files
    into a single DataFrame.
    """
    
    cleaned_frames = [] #Empty list to add cleaned df (separate FBS csv's)

    for filename in sorted(os.listdir(path_to_fbs)): #Iterates thru all CSB files in the directory in alphabetical order 
        if not filename.endswith(".csv"):
            continue

        if filename not in FILE_YEAR_RANGE: #Skips any CSV not in the File year range configuration directory 
            print(f"Skipping unrecognised file: {filename}")
            continue
        
        #Unpacks the year range tuple for files included in the FILE_YEAR_RANGE
        start, end = FILE_YEAR_RANGE[filename]
        
        filepath = os.path.join(path_to_fbs, filename)

        df = load_single_fbs_file(filepath)      #loads the file with the correct encoding & unwanted rows/col stated at the top
        
        df = filter_years(df, start, end)        #Filters to only the years interested in (change based on use case)
       
        cleaned_frames.append(df)

    if not cleaned_frames: #Raise an error if no valid files were found
        raise FileNotFoundError(f"No valid FBS CSVs found in {path_to_fbs}")

    if len(cleaned_frames) == 1: #When only one file was found no mergeing is required
        return cleaned_frames[0]
    
    # Merge all frames on shared ID columns (everything that isn't a year)
    id_cols = [c for c in cleaned_frames[0].columns if not is_year_col(c)]  #Get all non year columns (used as keys to merge by )
    
    merged = cleaned_frames[0]
    for frame in cleaned_frames[1:]:
        merged = merged.merge(frame, on=id_cols, how="outer") #merge based on id cols using outer --> rows that exist in one file but not others are kept (NaN fill missing year cols)

    #Finds all year columns and fills Nan with zero 
    year_cols = [c for c in merged.columns if is_year_col(c)] 
    
    merged[year_cols] = merged[year_cols].fillna(0)
   
    #Group cvountries together 
    merged = merged.groupby(id_cols, as_index=False)[year_cols].sum()  

    #Add ISO col for downscaling 
    merged = add_iso3_column(df=merged, column="Country")
    
    return merged

def main():
    fbs_path = r"X:\FoodSys\Data\Input\FBS_RAW_Files"
    Output_Path = r"X:\FoodSys\Data\Clean\FBS_Cleaned_2000-2020.csv"
    result = load_and_merge_fbs(fbs_path)

    #Save the merged files to the output location 
    result.to_csv(Output_Path, index = False)

if __name__ == "__main__":
    main()