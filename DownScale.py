""" File for Downscaling FAO onto SPAM (Spatial Surrogate)"""
#------------- IMPORTS --------------# 
import pandas as pd 
import xarray as xr 
import numpy as np
import sesame as ssm
from collections import defaultdict

def Clean_FAO_to_SPAM_Mapping(Mapping_csv: pd.DataFrame) -> pd.DataFrame:
    """ Trim whitespace from all string columns in the mapping table"""
    Mapping_df = Mapping_csv.copy() # Make a copy so do original DF isn't changed 

    Mapping_df = Mapping_df.loc[:, ~Mapping_df.columns.str.startswith("Unnamed")] # Drop blank columns from the double-comma CSV formatting


    String_cols = Mapping_df.select_dtypes(include="object").columns
    for col in String_cols:
       Mapping_df[col] = Mapping_df[col].str.strip()
    return Mapping_df

#For with medium confidence: 1:2 mappings
def Parse_Surrogates(Multi_surrogates) -> list[str]:
    """
    Turn crops like 'pmil, smil' or 'whea' into clean lists:
      'pmil, smil' -> ['pmil', 'smil']
      'whea'       -> ['whea']
    """

    Surrogate = str(Multi_surrogates)
    
    #If they have multiple split into individual 
    Indiv_Surrogates= Surrogate.split(",")
    
    Cleaned_list = []

    for Indiv in Indiv_Surrogates:
        cleaned = Indiv.strip() 
        if cleaned !="":
            Cleaned_list.append(cleaned)

    return Cleaned_list

#----- Function for linear interpolation for years in FBS but no SPAM ----#
def Interpolate_SPAM_annual(SPAM: xr.Dataset ):
    Target_Years = np.arange(2000,2021)
    SPAM_Interpolation = SPAM.interp(time=Target_Years, kwargs={"fill_value": np.nan}) #Nan for years before first surrogate
    
    SPAM_Interpolation = SPAM_Interpolation.bfill(dim="time").ffill(dim="time")  # carry nearest anchor into gap years

    

    return SPAM_Interpolation


def Build_FBS_Surrogates(SPAM_ds: xr.Dataset, Mapping_df: pd.DataFrame) -> xr.Dataset:
    """ Build a surrogate time series per FBS item using the Mapping"""
    
    Per_FBS_year: dict[str,dict[int, xr.DataArray]] = defaultdict[str,dict](dict)
    

    for (FBS_name, year), sub in Mapping_df.groupby(["FBS_Name","Year"]):
        combined: xr.DataArray | None = None

        #Sub is a df representing all rows in the mapping csv that match the FBS_Name, Year pair
        for rows in sub["SPAM_Surrogates"].unique():
            for crop in Parse_Surrogates(rows):
                if crop not in SPAM_ds:
                    print(f"Warning {crop} not in the SPAM dataset for the year {year}")
                    continue
                
                #Use the raw SPAM value for that release year
                da = SPAM_ds[crop].sel(time=year) 
                if combined is None:
                    combined = da
                else:
                    combined = combined + da #Adds if multiple surrogates for that FBS item in that year
        
        if combined is None:
            print(f"No surrogate available for FBS '{FBS_name}' in year {year}")
            continue

        if(float(combined.sum()) == 0.0):
            print(f"Skipping zero anchor for {FBS_name}, in {year} - the nearest real anchor (spam release) will be used")
            continue 


        #For this FBS item in this year store the combined xr.dataarray (sum all SPAM crops for the combo)
        Per_FBS_year[FBS_name][int(year)] = combined

    #Build a time series per FBS item & interpolate annually
    fbs_vars: dict[str, xr.DataArray] = {}

    #FBS_name = outer dict key (fbs item name) and year dict = inner dict (year:xr.dataarray)
    for FBS_name, year_dict in Per_FBS_year.items():
        Years = sorted(year_dict.keys())

        #Concat along time using the original SPAM release years
        Series = xr.concat([year_dict[y] for y in Years], dim="time")

        #Replaces the default indices to actual years
        Series = Series.assign_coords(time=Years) 

        #Interpolate to 2000-2020 for this FBS Item 
        Interp_seroes = Interpolate_SPAM_annual(Series)
        fbs_vars[FBS_name] = Interp_seroes

    return xr.Dataset(fbs_vars)

#---------------- Function that maps FAO onto SPAM ----------# 
def Down_Scaling(Surrogates: xr.Dataset, #SPAM grided surgate (time )
                Source: pd.DataFrame,  #FBS country-item-year table
                Mapping: pd.DataFrame,
                ) -> xr.Dataset:

    #Build a cts surrogate series for all FBS items of interest 
    FBS_Surrogates = Build_FBS_Surrogates(Surrogates, Mapping)

    Per_crop = defaultdict(list)

    Target_years = range(2000,2021)

    for FBS_commodity in Mapping["FBS_Name"].unique():
        #Get the final name (same for all years)
        Final_Name = Mapping[Mapping["FBS_Name"] == FBS_commodity]["Final_Name"].iloc[0] # gets name of index (crop)

        if FBS_commodity not in FBS_Surrogates:
            print(f"FBS, '{FBS_commodity}' has no surrogate seroes - skipping")
            continue
        
        for year in Target_years:
            yr = str(year)
            if yr not in Source.columns: #Yr DNE in FBS
                print(f"The year {year} DNE")
                continue
        
            #Reduces FBS for only current FBS item
            FBS_subset = Source[Source["Item"] == FBS_commodity].copy()
            
            #SMTH wrong here 
            if FBS_subset[yr].sum() == 0:
                print(f"In the year {year} the sum for {FBS_commodity} is zero")
                continue


            #Convert to tonnes to match SPAM
            Converted_prod = f"prod_{year}"
            FBS_subset[Converted_prod] = FBS_subset[yr] * 1000

            #----------------- All "cosmetic" to make sure the logs when verbose = true in the ssm call make sense --------#
            available_years = Mapping[Mapping["FBS_Name"] == FBS_commodity]["Year"].unique().astype(int)
            
            nearest_release = min(available_years, key=lambda r: abs(r - year))
            
            sub = Mapping[(Mapping["FBS_Name"] == FBS_commodity) & (Mapping["Year"] == nearest_release)]
            crops = []
            for s in sub["SPAM_Surrogates"].unique():
                crops.extend(Parse_Surrogates(s))
            surrogate_label = "_".join(sorted(set(crops))) if crops else FBS_commodity
            #-----------------------Setting up surrogates -----------------------------#

            # Extract the FBS-specific surrogate for this year (already built from SPAM)
            surrogate_da = FBS_Surrogates[FBS_commodity].sel(time=[year])
           
            # Name the surrogate variable by the underlying SPAM crops
            surrogate_ds = surrogate_da.to_dataset(name=surrogate_label)

            print(f"The totals for {FBS_commodity} in the year {year}")
            ds_year = ssm.table_2_grid(
                surrogate_data      = surrogate_ds,
                surrogate_variable  = surrogate_label,
                tabular_data        = FBS_subset,
                tabular_column      = Converted_prod,
                variable_name       = Final_Name,
                long_name           = f"{Final_Name} production in {year}",
                units               = 'tonne',
                source              = None,
                zero_is_value       = True,
                normalize_by_area   = False,
                verbose             = True
    
            )

            #Attach time coord back  --> #Gets the data arr for curr crop (lat,lon) adds a time dim than sets it to the year 

            data_array = ds_year[Final_Name].expand_dims(time=[year]) 
            Per_crop[Final_Name].append(data_array) 


    
    ssmds = []  
    for name, da_list in Per_crop.items():
        da_time = xr.concat(da_list, dim="time").sortby("time")
        ssmds.append(da_time.to_dataset(name=name))

    final_ds = xr.merge(ssmds)

    return final_ds
   


#------------------- xxxxxxxxxxxxxxxxx -------------------#
def main():
    """ Load input datasets """
    SPAM_Cleaned = xr.open_dataset(r"x:\FoodSys\Data\Clean\SPAM_Cleaned.nc")
    
    FBS_cleaned = pd.read_csv(r"x:\FoodSys\Data\Clean\FBS_Cleaned_2000-2020.csv") 
    
    FAO_to_SPAM_Mapping_raw = pd.read_csv(r"x:\FoodSys\Data\Mappings\Final_MAP.csv") 

    downscaled = Down_Scaling(SPAM_Cleaned, FBS_cleaned, FAO_to_SPAM_Mapping_raw)

    Output_Path = r"X:\FoodSys\Data\Output\FINAL.nc"

    downscaled.to_netcdf(Output_Path)
    
if __name__ == "__main__":
    main()
