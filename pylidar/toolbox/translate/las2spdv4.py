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

FIRST_RETURN = las.FIRST_RETURN
LAST_RETURN = las.LAST_RETURN

PULSE_DEFAULT_GAINS = {'X_ORIGIN':100.0,'Y_ORIGIN':100.0,'Z_ORIGIN':100.0,
    'AZIMUTH':100.0,'ZENITH':100.0,'X_IDX':100.0,'Y_IDX':100.0}
PULSE_DEFAULT_OFFSETS = {'X_ORIGIN':0.0,'Y_ORIGIN':0.0,'Z_ORIGIN':0.0,
    'AZIMUTH':0.0,'ZENITH':0.0,'X_IDX':0.0,'Y_IDX':0.0}

POINT_DEFAULT_GAINS = {'X':100.0, 'Y':100.0, 'Z':100.0, 'HEIGHT': 100.0}
POINT_DEFAULT_OFFSETS = {'X':0.0, 'Y':0.0, 'Z':-100.0, 'HEIGHT': -100.0}

WAVEFORM_DEFAULT_GAINS = {'RANGE_TO_WAVEFORM_START':100.0}
WAVEFORM_DEFAULT_OFFSETS = {'RANGE_TO_WAVEFORM_START':0.0}

def rangeFunc(data, rangeDict):
    """
    Called by translate() and used to determine range for fields
    required by SPD V4 scaling and header fields.
    """
    pulses = data.input1.getPulses()
    points = data.input1.getPoints()
    waveformInfo = data.input1.getWaveformInfo()

    if pulses.size > 0:
        if 'NUMBER_OF_PULSES' not in rangeDict['header']:
            rangeDict['header']['NUMBER_OF_PULSES'] = pulses.size
        else:
            rangeDict['header']['NUMBER_OF_PULSES'] += pulses.size
        for field in spdv4.PULSE_SCALED_FIELDS:
            # this is a field we need to save the scaling for
            if field in pulses.dtype.names:
                minKey = field + '_MIN'
                maxKey = field + '_MAX'
                minVal = pulses[field].min()
                maxVal = pulses[field].max()
                if (minKey not in rangeDict['pulses'] or 
                        minVal < rangeDict['pulses'][minKey]):
                    rangeDict['pulses'][minKey] = minVal
                if (maxKey not in rangeDict['pulses'] or 
                        maxVal > rangeDict['pulses'][maxKey]):
                    rangeDict['pulses'][maxKey] = maxVal
    
    if points.size > 0:
        if 'NUMBER_OF_POINTS' not in rangeDict['header']:
            rangeDict['header']['NUMBER_OF_POINTS'] = points.size
        else:
            rangeDict['header']['NUMBER_OF_POINTS'] += points.size
        for field in spdv4.POINT_SCALED_FIELDS:
            # this is a field we need to save the scaling for
            if field in points.dtype.names:
                minKey = field + '_MIN'
                maxKey = field + '_MAX'
                minVal = points[field].min()
                maxVal = points[field].max()
                if (minKey not in rangeDict['points'] or 
                        minVal < rangeDict['points'][minKey]):
                    rangeDict['points'][minKey] = minVal
                    rangeDict['header'][minKey] = minVal
                if (maxKey not in rangeDict['points'] or 
                        maxVal > rangeDict['points'][maxKey]):
                    rangeDict['points'][maxKey] = maxVal
                    rangeDict['header'][maxKey] = maxVal
    
    if waveformInfo.size > 0:      
        if 'NUMBER_OF_WAVEFORMS' not in rangeDict['header']:        
            rangeDict['header']['NUMBER_OF_WAVEFORMS'] = waveformInfo.size
        else:
            rangeDict['header']['NUMBER_OF_WAVEFORMS'] += waveformInfo.size        
        for field in spdv4.WAVEFORM_SCALED_FIELDS:
            # this is a field we need to save the scaling for
            if field in waveformInfo.dtype.names:
                minKey = field + '_MIN'
                maxKey = field + '_MAX'
                minVal = waveformInfo[field].min()
                maxVal = waveformInfo[field].max()
                if (minKey not in rangeDict['waveforms'] or 
                        minVal < rangeDict['waveforms'][minKey]):
                    rangeDict['waveforms'][minKey] = minVal
                if (maxKey not in rangeDict['waveforms'] or 
                        maxVal > rangeDict['waveforms'][maxKey]):
                    rangeDict['waveforms'][maxKey] = maxVal

def setOutputScaling(rangeDict, output):
    """
    Set the scaling on the output SPD V4 file using info gathered
    by rangeFunc.
    """
    # pulses
    for key in rangeDict['pulses'].keys():
        if key.endswith('_MIN'):
            field = key[0:-4]
            if field in PULSE_DEFAULT_GAINS:
                # use the scaling we already have
                checkScalingPositive(PULSE_DEFAULT_GAINS[field], 
                        PULSE_DEFAULT_OFFSETS[field], 
                        rangeDict['pulses'][key], key)
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_PULSES, 
                        PULSE_DEFAULT_GAINS[field], 
                        PULSE_DEFAULT_OFFSETS[field])
            else:
                # extract the _MAX also and set the scaling
                minVal = rangeDict['pulses'][key]
                maxVal = rangeDict['pulses'][key.replace('_MIN','_MAX')]            
                gain = np.iinfo(spdv4.PULSE_FIELDS[field]).max / (maxVal - minVal)
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_PULSES, 
                        gain, minVal)

    # points
    for key in rangeDict['points'].keys():
        if key.endswith('_MIN'):
            field = key[0:-4]            
            if field in POINT_DEFAULT_GAINS:
                # use the scaling we already have
                checkScalingPositive(POINT_DEFAULT_GAINS[field], 
                        POINT_DEFAULT_OFFSETS[field], 
                        rangeDict['points'][key], key)
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_POINTS, 
                        POINT_DEFAULT_GAINS[field], POINT_DEFAULT_OFFSETS[field])
            else:
                # extract the _MAX also and set the scaling
                minVal = rangeDict['points'][key]
                maxVal = rangeDict['points'][key.replace('_MIN','_MAX')]
                if maxVal == minVal:
                    gain = 1.0
                else:
                    gain = np.iinfo(spdv4.POINT_FIELDS[field]).max / (maxVal - minVal)
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_POINTS, gain, minVal)

    # waveforms
    for key in rangeDict['waveforms'].keys():
        if key.endswith('_MIN'):
            field = key[0:-4]
            if field in WAVEFORM_DEFAULT_GAINS:
                # use the scaling we already have
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_WAVEFORMS, 
                        WAVEFORM_DEFAULT_GAINS[field], 
                        WAVEFORM_DEFAULT_OFFSETS[field])
            else:
                # extract the _MAX also and set the scaling
                minVal = rangeDict['waveforms'][key]
                maxVal = rangeDict['waveforms'][key.replace('_MIN','_MAX')]
                gain = np.iinfo(spdv4.WAVEFORM_FIELDS[field]).max / (maxVal - minVal)
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_WAVEFORMS, 
                    gain, minVal)

def checkScalingPositive(gain, offset, minVal, varName):
    """
    Check that the given gain and offset will not give rise to
    negative values when applied to the minimum value. 
    """
    scaledVal = (minVal - offset) * gain
    if scaledVal < 0:
        msg = ("Scaling for %s gives negative values, " + 
                "which SPD4 will not cope with. Over-ride defaults on " +
                "commandline. " % varName)
        raise generic.LiDARInvalidSetting(msg)

def overRideDefaultScalings(scaling):
    """
    Any scalings given on the commandline should over-ride 
    the default behaviours.
    Assumes that varName is unique between points and pulses.
    Changes global vars which is a bit dodgy.
    """
    for (varName, gainStr, offsetStr) in scaling:
        gain = float(gainStr)
        offset = float(offsetStr)
        if varName in POINT_DEFAULT_GAINS:
            POINT_DEFAULT_GAINS[varName] = gain
            POINT_DEFAULT_OFFSETS[varName] = offset
        elif varName in PULSE_DEFAULT_GAINS:
            PULSE_DEFAULT_GAINS[varName] = gain
            PULSE_DEFAULT_OFFSETS[varName] = offset

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
    output.setHeader(h)

def transFunc(data, otherDict):
    """
    Called from pylidar. Does the actual conversion to SPD V4
    """
    pulses = data.input1.getPulses()
    points = data.input1.getPointsByPulse()
    waveformInfo = data.input1.getWaveformInfo()
    revc = data.input1.getReceived()
    
    # set scaling and write header
    if data.info.isFirstBlock():
        setOutputScaling(otherDict, data.output1)
        lasInfo = data.input1.getHeader()
        setHeaderValues(otherDict, lasInfo, data.output1)
        
    data.output1.setPoints(points)
    data.output1.setPulses(pulses)
    if waveformInfo is not None and waveformInfo.size > 0:
        data.output1.setWaveformInfo(waveformInfo)
    if revc is not None and revc.size > 0:
        data.output1.setReceived(revc)

def translate(info, infile, outfile, spatial, scaling, epsg, binSize, pulseIndex):
    """
    Main function
    """
    if scaling is not None:
        overRideDefaultScalings(scaling)

    if epsg is None and len(info.wkt) == 0:
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
    
    dataFiles.input1 = lidarprocessor.LidarFile(las, lidarprocessor.READ)
    if pulseIndex == 'FIRST_RETURN':
        dataFiles.input1.setLiDARDriverOption('PULSE_INDEX', FIRST_RETURN)
    elif pulseIndex == 'LAST_RETURN':
        dataFiles.input1.setLiDARDriverOption('PULSE_INDEX', LAST_RETURN)
    else:
        raise SystemExit("Pulse index argument not recognised.")
    if not buildpulses:
        dataFiles.input1.setLiDARDriverOption('BUILD_PULSES', False)
    if spatial:
        dataFiles.input1.setLiDARDriverOption('BIN_SIZE', float(binSize))

    controls = lidarprocessor.Controls()
    progress = cuiprogress.GDALProgressBar()
    controls.setProgress(progress)
    controls.setSpatialProcessing(spatial)
    
    # now read through the file and get the range of values for fields 
    # that need scaling.
    print('Determining range of input data fields...')
   
    otherDict = {'pulses':{},'points':{},'waveforms':{},'header':{},'epsg':epsg}
    lidarprocessor.doProcessing(rangeFunc, dataFiles, controls=controls, 
                    otherArgs=otherDict)

    print('Converting %s to SPD V4...'%las)
    dataFiles.output1 = lidarprocessor.LidarFile(spd, lidarprocessor.CREATE)
    dataFiles.output1.setLiDARDriver('SPDV4')

    lidarprocessor.doProcessing(transFunc, dataFiles, controls=controls, 
                    otherArgs=otherDict)
