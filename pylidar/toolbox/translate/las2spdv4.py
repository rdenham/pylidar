"""
Handles conversion between LAS and SPDV4 formats
"""

# This file is part of PyLidar
# Copyright (C) 2015 John Armston, Pete Bunting, Neil Flood, Sam Gillingham
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import print_function, division

import numpy
from pylidar import lidarprocessor
from pylidar.lidarformats import generic
from pylidar.lidarformats import spdv4
from pylidar.lidarformats import las
from rios import cuiprogress
from osgeo import osr

from . import translatecommon

def setHeaderValues(rangeDict, lasInfo, output):
    """
    Set the header values in the output SPD V4 file using info gathered
    by rangeFunc
    """
    h = rangeDict['header']
    if rangeDict['epsg'] is not None:
        sr = osr.SpatialReference()
        sr.ImportFromEPSG(rangeDict['epsg'])
        h['SPATIAL_REFERENCE'] = sr.ExportToWkt()    
    else:
        h['SPATIAL_REFERENCE'] = lasInfo.wkt
    output.setHeader(h)

def transFunc(data, otherDict):
    """
    Called from lidarprocessor. Does the actual conversion to SPD V4
    """
    pulses = data.input1.getPulses()
    points = data.input1.getPointsByPulse()
    waveformInfo = data.input1.getWaveformInfo()
    revc = data.input1.getReceived()
    
    # set scaling and write header
    if data.info.isFirstBlock():
        translatecommon.setOutputScaling(otherDict, data.output1)
        lasInfo = data.input1.getHeader()
        setHeaderValues(otherDict, lasInfo, data.output1)
        
    data.output1.setPoints(points)
    data.output1.setPulses(pulses)
    if waveformInfo is not None and waveformInfo.size > 0:
        data.output1.setWaveformInfo(waveformInfo)
    if revc is not None and revc.size > 0:
        data.output1.setReceived(revc)

def translate(info, infile, outfile, expectRange, spatial, scaling, epsg, 
        binSize, buildPulses, pulseIndex):
    """
    Main function which does the work.

    * Info is a fileinfo object for the input file.
    * infile and outfile are paths to the input and output files respectively.
    * expectRange is a list of tuples with (type, varname, min, max).
    * spatial is True or False - dictates whether we are processing spatially or not.
        If True then spatial index will be created on the output file on the fly.
    * scaling is a list of tuples with (type, varname, gain, offset).
    * if epsg is not None should be a EPSG number to use as the coord system
    * binSize is the used by the LAS spatial index
    * buildPulses dictates whether to attempt to build the pulse structure
    * pulseIndex should be 'FIRST_RETURN' or 'LAST_RETURN' and determines how the
        pulses are indexed.
    """
    scalingsDict = translatecommon.overRideDefaultScalings(scaling)

    if epsg is None and (info.wkt is None or len(info.wkt) == 0):
        msg = 'No projection set in las file. Must set EPSG on command line'
        raise generic.LiDARInvalidSetting(msg)

    if spatial and not info.hasSpatialIndex:
        msg = 'Spatial processing requested but file does not have spatial index'    
        raise generic.LiDARInvalidSetting(msg)

    if spatial and binSize is None:
        msg = "For spatial processing, the bin size must be set"
        raise generic.LiDARInvalidSetting(msg)

    # set up the variables
    dataFiles = lidarprocessor.DataFiles()
    
    dataFiles.input1 = lidarprocessor.LidarFile(infile, lidarprocessor.READ)
    if pulseIndex == 'FIRST_RETURN':
        dataFiles.input1.setLiDARDriverOption('PULSE_INDEX', las.FIRST_RETURN)
    elif pulseIndex == 'LAST_RETURN':
        dataFiles.input1.setLiDARDriverOption('PULSE_INDEX', las.LAST_RETURN)
    else:
        msg = "Pulse index argument not recognised."
        raise generic.LiDARInvalidSetting(msg)
    if not buildPulses:
        dataFiles.input1.setLiDARDriverOption('BUILD_PULSES', False)
    if spatial:
        dataFiles.input1.setLiDARDriverOption('BIN_SIZE', float(binSize))

    controls = lidarprocessor.Controls()
    progress = cuiprogress.GDALProgressBar()
    controls.setProgress(progress)
    controls.setSpatialProcessing(spatial)
    
    # now read through the file and get the range of values for fields 
    # that need scaling.
    otherDict = translatecommon.getRange(dataFiles.input1, spatial, expectRange)

    print('Converting %s to SPD V4...' % infile)
    dataFiles.output1 = lidarprocessor.LidarFile(outfile, lidarprocessor.CREATE)
    dataFiles.output1.setLiDARDriver('SPDV4')

    # also need the default/overriden scaling
    otherDict['scaling'] = scalingsDict
    # and epsg
    otherDict['epsg'] = epsg 
    # set index type if spatial - always cartesian for LAS (??)
    if spatial:
        otherDict['header']['INDEX_TYPE'] = spdv4.SPDV4_INDEX_CARTESIAN

    lidarprocessor.doProcessing(transFunc, dataFiles, controls=controls, 
                    otherArgs=otherDict)

