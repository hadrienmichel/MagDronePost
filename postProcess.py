'''
Author: Hadrien Michel (ULiège)
e-mail: hadrien[dot]michel[at]uliege[dot]be
--------------------------------------------

This script is intended to use files pre-processed using 
MagComPy (Kaub et al., 2021) and convert the results into 
GeoTiff files.

It takes in the input section the different arguments:
    - dir (str): the directory in which the files are located
    - data (str): the name of the file to process
    - resultsTif (str): the name of the file in which the 
                        reduced-to-pole data is saved
    - latitude (float): the latitude of the explored site in 
                        decimal degrees
    - longitude (float): the longitude of the explored site
                         in decimal degrees
    - altitude (float): the altitude of the site AMSL in km
    - date (str): the date of acquistion of the data in format 
                  yyyy-mm-dd

The pre-processed files are first converted to a gridded array 
using VERDE (Fatiando A Terra), and then the interpolated data is 
reduced to the pole using HARMONICA (Fatiando A Terra).

The magnetic field properties on site are calculated using the 
web API from BGS (magnteic_field_calculator on GitHub).

Finally, the results are converted into a raster file (*.tif)
using rasterio.

This script is provided as-is without any warranty.
'''
import numpy as np
import pandas as pd
import cartopy.crs as ccrs

import verde as vd
import harmonica as hc

from matplotlib import pyplot as plt

import rasterio

from magnetic_field_calculator import MagneticFieldCalculator

##########################################################################################
##                                                                                      ##
##                                     Script inputs                                    ##
##                                                                                      ##
##########################################################################################         
dir = "//fsa-gpa-nas01.fsa.uliege.priv/geophysicalData/Drones/20230504-VielleMontagne/Mag/"
data = "MeasureDir1_PostProcess1.csv"

resultsTif = 'Reduced2PoleDataSens.tif'

latitude = 50.6297580
longitude=5.478596
altitude=0.200
date='2023-05-04'

fieldCompute = ' B1Tot'

##########################################################################################
##                                                                                      ##
##                     Loading the files and computing parameters                       ##
##                                                                                      ##
##########################################################################################

data = pd.read_csv(dir+data, sep=';')

calculator = MagneticFieldCalculator(model='wmm')

results = calculator.calculate(
    latitude=latitude, # In deg
    longitude=longitude, # In deg
    altitude=altitude, # In km
    date=date # Date in yyyy-mm-dd
)
fieldCalc = results['field-value']
inclinationSite = fieldCalc['inclination']['value']# 65.8927
declinationSite = fieldCalc['declination']['value']# 2.1025
totalIntensity = fieldCalc['total-intensity']['value']

print(f'The calculated magnetic field has the following parameters:\n\t- Total Field [nT]: {totalIntensity}\n\t- Inclination [°]: {inclinationSite}\n\t- Declination [°]: {declinationSite}')

print(data.head())

##########################################################################################
##                                                                                      ##
##                                 Post-processing of file                              ##
##                                                                                      ##
##########################################################################################

spacingBlock = 5 # in m
reducer = vd.BlockReduce(reduction=np.median, spacing=spacingBlock)
coordinates, magField = reducer.filter((data[' X_BD72_m'], data[' Y_BD72_m']), data[fieldCompute]-48925)

east, north = coordinates

print("Original data size:", data[fieldCompute].size)
print("Decimated data size:", magField.size)

plt.figure()
ax = plt.axes(projection=ccrs.epsg(31370))
ax.set_title(f"{int(spacingBlock)} m Block Reduced Dataset")
# Plot the bathymetry as colored circles.
plt.scatter(east, north, c=magField, s=5)
plt.colorbar().set_label("Magnetic Anomaly [nT]")
# Use a utility function to setup the tick labels and land feature
# vd.datasets.setup_baja_bathymetry_map(ax)
plt.show(block=False)

spline = vd.Spline(mindist=500, damping=1e-10)

spline.fit(coordinates, magField)

# # Only available for SplineCV
# # We can show the best R² score obtained in the cross-validation
# print("\nScore: {:.3f}".format(spline.scores_.max()))

# # And then the best spline parameters that produced this high score.
# print("\nBest spline configuration:")
# print("  mindist:", spline.mindist_)
# print("  damping:", spline.damping_)

region=vd.pad_region(vd.get_region(coordinates),50)

grid_full = spline.grid(
    region=region,
    spacing=1,
    dims=["easting", "northing"],
    data_names="total_field_anomaly",
)

grid = vd.distance_mask(
    coordinates, maxdist=20, grid=grid_full)

# Plot the grid and the original data points
plt.figure(figsize=(8, 6))
ax = plt.axes(projection=ccrs.epsg(31370))
ax.set_title("Magnetic anomaly gridded with biharmonic spline")
ax.plot(*coordinates, ".k", markersize=1)
tmp = grid.total_field_anomaly.plot.pcolormesh(
    ax=ax, cmap="seismic", add_colorbar=False
)
plt.colorbar(tmp).set_label("Magnetic Anomaly [nT]")
plt.show(block=False)

###### Reduction to pole of the dataset:
if grid_full.isnull().any():
    print('They are nan(s) in the dataset!')
    filled = grid_full.total_field_anomaly.fillna(np.nanmedian(grid_full.total_field_anomaly))
else:
    filled = grid_full.copy()

rtp_grid = hc.reduction_to_pole(filled, inclination=inclinationSite, declination=declinationSite)
gridReduced = vd.distance_mask(
    coordinates, maxdist=20, grid=rtp_grid.to_dataset(name='total_field_anomaly'))
# gridReduced = vd.distance_mask(
    # coordinates, maxdist=20, grid=gridReduced)
# print(gridReduced)

# Plot the grid and the original data points
plt.figure(figsize=(8, 6))
ax = plt.axes(projection=ccrs.epsg(31370))
ax.set_title("Magnetic anomaly reduced to pole")
ax.plot(*coordinates, ".k", markersize=1)
tmp = gridReduced.total_field_anomaly.plot.pcolormesh(
    ax=ax, cmap="seismic", add_colorbar=False
)
plt.colorbar(tmp).set_label("Reduced Magnetic Anomaly [nT]")
plt.show(block=False)

##########################################################################################
##                                                                                      ##
##                                Saving the grid in GeoTiff                            ##
##                                                                                      ##
##########################################################################################

gridReduced = gridReduced.to_array()
reducedMag = gridReduced.values
coordinates = gridReduced.coords

# Define the Lambert 72 projection
lambert_72 = {'init': 'EPSG:31370'}


reducedMag = np.flipud(np.squeeze(reducedMag))

with rasterio.open(dir+resultsTif, 
                   'w', 
                   driver='GTiff', 
                   height=reducedMag.shape[0], 
                   width=reducedMag.shape[1], 
                   count=1, 
                   dtype=reducedMag.dtype, 
                   crs=lambert_72, 
                   transform=rasterio.transform.from_bounds(region[0], region[2], region[1], region[3], reducedMag.shape[1], reducedMag.shape[0])
    ) as dst:
    dst.write(reducedMag, 1)

plt.show()