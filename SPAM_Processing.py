# ---------------- NOTES ------------------------# 
"""
Done: Just disregarded any not.tif suffixes --> The SPAM_RAW_2005 file has 3 files per year as there are tif, tfw and tiff aux files so do not run with it yet 

Done --> Should convert the crop name to lowercase to match that of the SPAM_name column in the FAO to SPAM mapping 

DONE: Made a nested dictionary where within the 2nd one it maps year to path to tif file  ---> When looping thru each subdirectory for the tiff files make sure they are PATHS as thats what sesame needs

DONE: Made two subfolders of input --> Currently FAO is in the same input folder either put SPAM in directory 

DONE?: Checked for duplicates but not yet correct crop count --> Make sure that the crops for each year are actual those that should be there i.e. no duplicates and proper length 

Done: Check the sums before and after regridding I think they match 

NOT DONE: othe is zero for 2000 

overest grid cells but in grid cells will be underestimated

"""
# -------------- Library imports ----------------# 
import sesame as ssm
import rasterio 
import pandas as pd 
import numpy as np
import xarray as xr

#File imports
import os 
import tempfile
import re


#Crops not interested in due to non calories or do not have an FBS Mapping  or in the case of othe have no valkues 
Crops_to_remove = {2000:{"COTT","OFIB","othe"},2005:{"COTT","OFIB","TOBA"},
                           2010:{"COTT","OFIB","TOBA"},2020:{"COTT","OFIB","TOBA","RUBB","onio"}}


#---------------------------------------- Helper functions --------------------------------------#

def get_year(SPAM_Folder_yr: str ) -> int: 
    """Extracting the year for each SPAM year folder to act as the time dimension in the xarray"""
    pattern = re.search(r"\d{4}",SPAM_Folder_yr)
    return int(pattern.group())

def extract_crop_name(Tiff_path: str ,SPAM_Year: int) -> str:
    """ Extracting the crop name for each tiff file (Individual crop) to act a indentifier"""
    
    FileName =os.path.basename(Tiff_path)   #Extracts just file name 

    Stem = os.path.splitext(FileName)[0]    #Remove .tif extension

    Parts = Stem.split("_")                 

    if SPAM_Year in (2000,2010):
        return Parts[3]
    elif SPAM_Year in(2005, 2020):
        return Parts[4]

#------------- Normalizing nodata values across all years (set to zero) -----------#
""" 
Each year uses different ways to describe no data pixels for example: 
Year 2000 & 2010: Nodata = - 1
Year 2005: Nodata =  -3.40 x 10^38
Year 2020: Nodata = nan 
"""
#Returns a path to a cleaned temp GEotiff file for a given crop based on the metadata
def Normalize_SPAM_nodata_values(Crop_tif_path: str) -> str:
    with rasterio.open(Crop_tif_path) as src: 
        
        #The actual data
        arr = src.read(1).astype("float32")
       
        All_Meta_Data = src.profile.copy()  #Extract the meta data (copy so do not modify Original)

        Nodata_Representation = src.nodata  #Extract the nodata representation

    #Convert the nodata representation to nan
    if Nodata_Representation is not None:
        if np.isnan(Nodata_Representation):
            pass
        else: 
            arr[arr== Nodata_Representation] = np.nan

    #Convert Nan to zero (no crop production)
    arr = np.nan_to_num(arr, nan= 0.0)

    #Update metadata 
    All_Meta_Data.update(nodata=0.0, dtype="float32")

    #Write the cleaned raster to a temp file 
    temp_tif_path = tempfile.NamedTemporaryFile(suffix=".tif",delete=False)
    temp_tif_path.close() # Closing the temp file
    with rasterio.open(temp_tif_path.name,"w",**All_Meta_Data) as dst:
        dst.write(arr,1)

    return temp_tif_path.name
#-------------------------------- Function for loading the SPAM data --------------------#
def Loading_SPAM_Data(Raw_SPAM_Data:str) -> dict[int,dict[str,str]]:
    

    #Initialize array to store all crops for each year (2000,2005,2010,2020)
    Year_to_crop_paths = {}

    #First level of directories 
    for SPAM_Release in os.listdir(Raw_SPAM_Data):
        
        #Making sure the FAO directory isn't iterated through 
        if "SPAM" not in SPAM_Release:
            continue
        
        Full_path = os.path.join(Raw_SPAM_Data, SPAM_Release)

    
        # Extract year to act as the key for the dictionary
        Year = get_year(SPAM_Release)

        #Array to store each crop per year 
        Crop_Path = {}

        #Go thru all the tiff files (1 per crop) in the SPAM release 
        for tiff_file in os.listdir(Full_path):


            # SKIP metadata files (.tfw and .tif.sux.hml)
            if not tiff_file.lower().endswith(".tif"):
                continue
            
            tiff_path = os.path.join(Full_path, tiff_file)

            Crop_name = extract_crop_name(tiff_path,Year).lower()

            #Remove no calory or non FBS crops
            Excluded_crops = {c.lower() for c in Crops_to_remove.get(Year, set())}
            if Crop_name in Excluded_crops:
                continue
            
            #Check for duplicates
            if Crop_name in Crop_Path:
                print(f'Duplicate crop {Crop_name} in {Year}')

            #Nested dictionary where the key is the crop and value is the path
            Crop_Path[Crop_name] = tiff_path
        
        Year_to_crop_paths[Year] = Crop_Path

    return Year_to_crop_paths
#----------------------------------------Function for the sesame call (regridding) --------------------------------------#
def Convert_to_netcdf(Path_to_SPAM_Directory: str) -> xr.Dataset :

    Loaded_SPAM_tif = Loading_SPAM_Data(Path_to_SPAM_Directory)

    #Will include all years crops at end
    All_Years_ds = []


    for year, crop_dict in Loaded_SPAM_tif.items():

        Per_Crop_ds = []

        for crop, paths in crop_dict.items():
            
            # Metadata check for each crop
            print(year,crop)
        
            
            Cleaned_path = Normalize_SPAM_nodata_values(paths)
            #DEbugging check
            with rasterio.open(Cleaned_path) as src:
                arr = src.read(1, masked=False).astype("float64")
                print("NaNs in cleaned tif:", np.isnan(arr).sum())
                """
                print("CLEAN nodata metadata:", src.nodata)
                print("CLEAN min/max:", np.nanmin(a), np.nanmax(a))
                print("CLEAN nan count:", np.isnan(a).sum())
                print("CLEAN count < 0:", np.sum(a < 0))
                """
                #arr_before = src.read(1, masked=False).astype("float64")
                #sum_before = float(np.nansum(arr_before))

            ds = ssm.grid_2_grid(
                raster_data= Cleaned_path,
                agg_function="sum",
                variable_name= crop,
                long_name=f"{crop} SPAM",
                units="tonne",
                time=year,
                resolution=1,
                zero_is_value=True,
                verbose=True

            )
            print("NaNs after regridding:", ds[crop].isnull().sum().item())
            """
            # Sum AFTER regridding
            sum_after = float(ds[crop].values.sum())

            pct_diff = abs(sum_before - sum_after) / sum_before * 100 if sum_before != 0 else 0
            print(f"[{year}] {crop:<12} | before: {sum_before:>15,.1f} | after: {sum_after:>15,.1f} | diff: {pct_diff:.4f}%")
            """
            
            Per_Crop_ds.append(ds)
            os.remove(Cleaned_path)
        
        #merge all individual crops into a yearly xarray --
        Yearly_ds= xr.merge(Per_Crop_ds)
        print("NaNs after yearly merge:", Yearly_ds.to_array().isnull().sum().item())
    
        #Make sure time is correct
        Yearly_ds = Yearly_ds.assign_coords(time=[year])

        #Each iteration add the years complete dataset to the final ds 
        All_Years_ds.append(Yearly_ds)

    #Add the time dimension (concanate along time DIM)
    All_SPAM_ds = xr.concat(All_Years_ds, dim="time")
    print("NaNs after concat:", All_SPAM_ds.to_array().isnull().sum().item())
    

    return All_SPAM_ds

#----------------------------------------Function for running program --------------------------------------#

def main():
    
    #Dataset to clean
    Input_Path = r"X:\FoodSys\Data\Input\SPAM_Raw_All_years"

    #Function call
    result = Convert_to_netcdf(Input_Path)
    
    Output_Path = r"X:\FoodSys\Data\Clean\SPAM_Cleaned.nc"
    
    result.to_netcdf(Output_Path)

if __name__ == "__main__":
    main()