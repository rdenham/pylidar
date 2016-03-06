#!/usr/bin/env python

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

import sys
import optparse
import numpy
from pylidar import lidarprocessor
from pylidar.lidarformats import generic
from pylidar.lidarformats import spdv4
from rios import cuiprogress
from osgeo import osr

PULSE_DEFAULT_GAINS = {'X_ORIGIN':100.0,'Y_ORIGIN':100.0,'X_ORIGIN':100.0,'AZIMUTH':100.0,'ZENITH':100.0}
PULSE_DEFAULT_OFFSETS = {'X_ORIGIN':0.0,'Y_ORIGIN':0.0,'X_ORIGIN':0.0,'AZIMUTH':0.0,'ZENITH':0.0}

POINT_DEFAULT_GAINS = {'X':100.0, 'Y':100.0, 'Z':100.0}
POINT_DEFAULT_OFFSETS = {'X':0.0, 'Y':0.0, 'Z':0.0}

WAVEFORM_DEFAULT_GAINS = {'RANGE_TO_WAVEFORM_START':100.0}
WAVEFORM_DEFAULT_OFFSETS = {'RANGE_TO_WAVEFORM_START':0.0}


class CmdArgs(object):
    def __init__(self):
        p = optparse.OptionParser()
        p.add_option("--spatial", dest="spatial", 
            help="Process the data spatially. Specify 'yes' or 'no'. " +
            "Default is spatial if a spatial index exists.")
        p.add_option("--buildpulses", dest="buildpulses", default=False, action="store_true",
            help="Build pulse data structure. " +
            "Default is False.")
        p.add_option("--pulseindex", dest="pulseindex", default="FIRST_RETURN"
            help="Pulse index method. Set to FIRST_RETURN or LAST_RETURN. Default is FIRST_RETURN.")
        p.add_option("--binsize", "-b", dest="binSize",
            help="Bin size to use when processing spatially")
        p.add_option("--las", dest="las",
            help="Input las .las file")
        p.add_option("--spd", dest="spd",
            help="output SPD V4 file name")
        p.add_option("--epsg", dest="epsg", type=int,
            help="Set to EPSG to override")
            
        (options, args) = p.parse_args()
        self.__dict__.update(options.__dict__)

        if self.las is None or self.spd is None:
            p.print_help()
            sys.exit()


def rangeFunc(data, rangeDict):
    """
    Called by pylidar and used to determine range for fields
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
            if field in pulses.dtype.names:
                minKey = field + '_MIN'
                maxKey = field + '_MAX'
                minVal = pulses[field].min()
                maxVal = pulses[field].max()
                if minKey not in rangeDict['pulses'] or minVal < rangeDict['pulses'][minKey]:
                    rangeDict['pulses'][minKey] = minVal
                if maxKey not in rangeDict['pulses'] or maxVal > rangeDict['pulses'][maxKey]:
                    rangeDict['pulses'][maxKey] = maxVal
    
    if points.size > 0:
        if 'NUMBER_OF_POINTS' not in rangeDict['header']:
            rangeDict['header']['NUMBER_OF_POINTS'] = points.size
        else:
            rangeDict['header']['NUMBER_OF_POINTS'] += points.size
        for field in spdv4.POINT_SCALED_FIELDS:
            if field in points.dtype.names:
                minKey = field + '_MIN'
                maxKey = field + '_MAX'
                minVal = points[field].min()
                maxVal = points[field].max()
                if minKey not in rangeDict['points'] or minVal < rangeDict['points'][minKey]:
                    rangeDict['points'][minKey] = minVal
                    rangeDict['header'][minKey] = minVal
                if maxKey not in rangeDict['points'] or maxVal > rangeDict['points'][maxKey]:
                    rangeDict['points'][maxKey] = maxVal
                    rangeDict['header'][maxKey] = maxVal
    
    if waveformInfo.size > 0:      
        if 'NUMBER_OF_WAVEFORMS' not in rangeDict['header']:        
            rangeDict['header']['NUMBER_OF_WAVEFORMS'] = waveformInfo.size
        else:
            rangeDict['header']['NUMBER_OF_WAVEFORMS'] += waveformInfo.size        
        for field in spdv4.WAVEFORM_SCALED_FIELDS:
            if field in waveformInfo.dtype.names:
                minKey = field + '_MIN'
                maxKey = field + '_MAX'
                minVal = waveformInfo[field].min()
                maxVal = waveformInfo[field].max()
                if minKey not in rangeDict['waveforms'] or minVal < rangeDict['waveforms'][minKey]:
                    rangeDict['waveforms'][minKey] = minVal
                if maxKey not in rangeDict['waveforms'] or maxVal > rangeDict['waveforms'][maxKey]:
                    rangeDict['waveforms'][maxKey] = maxVal
    

def setOutputScaling(rangeDict, output, usedefaults=False):
    """
    Set the scaling on the output SPD V4 file using info gathered
    by rangeFunc.
    """
    for key in rangeDict['pulses'].keys():
        if key.endswith('_MIN'):
            field = key[0:-4]
            if field in PULSE_DEFAULT_GAINS:
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_PULSES, PULSE_DEFAULT_GAINS[field], PULSE_DEFAULT_OFFSETS[field])
            else:
                minVal = rangeDict['pulses'][key]
                maxVal = rangeDict['pulses'][key.replace('_MIN','_MAX')]            
                gain = np.iinfo(spdv4.PULSE_FIELDS[field]).max / (maxVal - minVal)
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_PULSES, gain, minVal)
    for key in rangeDict['points'].keys():
        if key.endswith('_MIN'):
            field = key[0:-4]            
            if field in POINT_DEFAULT_GAINS:
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_POINTS, POINT_DEFAULT_GAINS[field], POINT_DEFAULT_OFFSETS[field])            
            else:
                minVal = rangeDict['points'][key]
                maxVal = rangeDict['points'][key.replace('_MIN','_MAX')]
                gain = np.iinfo(spdv4.POINT_FIELDS[field]).max / (maxVal - minVal)
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_POINTS, gain, minVal)
    for key in rangeDict['waveforms'].keys():
        if key.endswith('_MIN'):
            field = key[0:-4]
            if field in WAVEFORM_DEFAULT_GAINS:
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_WAVEFORMS, WAVEFORM_DEFAULT_GAINS[field], WAVEFORM_DEFAULT_OFFSETS[field])            
            else:
                minVal = rangeDict['waveforms'][key]
                maxVal = rangeDict['waveforms'][key.replace('_MIN','_MAX')]
                gain = np.iinfo(spdv4.WAVEFORM_FIELDS[field]).max / (maxVal - minVal)
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_WAVEFORMS, gain, minVal)


def setHeaderValues(rangeDict, lasInfo, output, epsg=None):
    """
    Set the header values in the output SPD V4 file using info gathered
    by rangeFunc
    """
    h = rangeDict['header']
    if epsg is not None:
        sr = osr.SpatialReference()
        sr.ImportFromEPSG(epsg)
        header['SPATIAL_REFERENCE'] = sr.ExportToWkt()    
    output.setHeader(h)


def transFunc(data, rangeDict):
    """
    Called from pylidar. Does the actual conversion to SPD V4
    """
    pulses = data.input1.getPulses()
    points = data.input1.getPointsByPulse()
    waveformInfo = data.input1.getWaveformInfo()
    revc = data.input1.getReceived()
    
    # set scaling and write header
    if data.info.isFirstBlock():
        setOutputScaling(rangeDict, data.output1)
        lasInfo = data.input1.getHeader()
        setHeaderValues(rangeDict, lasInfo, data.output1)
        
    data.output1.setPoints(points)
    data.output1.setPulses(pulses)
    if waveformInfo is not None and waveformInfo.size > 0:
        data.output1.setWaveformInfo(waveformInfo)
    if revc is not None and revc.size > 0:
        data.output1.setReceived(revc)


def doTranslation(spatial, buildpulses, pulseindex, binSize, las, spd):
    """
    Does the translation between .las and SPD v4 format files.
    """
    # first we need to determine if the file is spatial or not
    info = generic.getLidarFileInfo(las)
    if spatial is not None:
        if spatial and not info.hasSpatialIndex:
            raise SystemExit("Spatial processing requested but file does not have spatial index")
    else:
        spatial = info.hasSpatialIndex
    
    if spatial and binSize is None:
        raise SystemExit("For spatial processing, the bin size (--binsize) must be set")
    
    # set up the variables
    dataFiles = lidarprocessor.DataFiles()
        
    dataFiles.input1 = lidarprocessor.LidarFile(las, lidarprocessor.READ)
    dataFiles.input1.setLiDARDriverOption('PULSE_INDEX', pulseindex)
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
   
    rangeDict = {'pulses':{},'points':{},'waveforms':{},'header':{}}
    lidarprocessor.doProcessing(rangeFunc, dataFiles, controls=controls, 
                    otherArgs=rangeDict)

    print('Converting to SPD V4...')
    dataFiles.output1 = lidarprocessor.LidarFile(spd, lidarprocessor.CREATE)
    dataFiles.output1.setLiDARDriver('SPDV4')

    lidarprocessor.doProcessing(transFunc, dataFiles, controls=controls, 
                    otherArgs=rangeDict)
    
if __name__ == '__main__':

    cmdargs = CmdArgs()
    
    spatial = None
    if cmdargs.spatial is not None:
        spatialStr = cmdargs.spatial.lower()
        if spatialStr != 'yes' and spatialStr != 'no':
            raise SystemExit("Must specify either 'yes' or 'no' for --spatial flag")
    
        spatial = (spatialStr == 'yes')
    
    doTranslation(spatial, cmdargs.buildpulses, cmdargs.pulseindex, cmdargs.binSize, cmdargs.las, cmdargs.spd)
    
