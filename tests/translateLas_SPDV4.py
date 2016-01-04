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
from pylidar import lidarprocessor
from pylidar.lidarformats import generic
from rios import cuiprogress

MAX_UINT16 = 2**16

class CmdArgs(object):
    def __init__(self):
        p = optparse.OptionParser()
        p.add_option("--spatial", dest="spatial", 
            help="process the data spatially. Specify 'yes' or 'no'. " +
            "Default is spatial if a spatial index exists.")
        p.add_option("--binsize", "-b", dest="binSize",
            help="bin size to use when processing spatially")
        p.add_option("--las", dest="las",
            help="input las .las file")
        p.add_option("--spd", dest="spd",
            help="output SPD V4 file name")
            
        (options, args) = p.parse_args()
        self.__dict__.update(options.__dict__)

        if self.las is None or self.spd is None:
            p.print_help()
            sys.exit()
    
def rangeFunc(data, rangeDict):
    """
    Called by pylidar and used to determine range for fields
    required by SPD V4 scaling.
    """
    pulses = data.input1.getPulses()
    points = data.input1.getPoints()
    waveformInfo = data.input1.getWaveformInfo()

    if pulses.size > 0:    
        for field in ('X_IDX', 'Y_IDX', 'X_ORIGIN', 'Y_ORIGIN', 'Z_ORIGIN', 
                'AZIMUTH', 'ZENITH'):
            minKey = 'pulse_' + field + '_min'
            maxKey = 'pulse_' + field + '_max'
            minVal = pulses[field].min()
            maxVal = pulses[field].max()
            if minKey not in rangeDict or minVal < rangeDict[minKey]:
                rangeDict[minKey] = minVal
            if maxKey not in rangeDict or maxVal > rangeDict[maxKey]:
                rangeDict[maxKey] = maxVal
        
    if points.size > 0:    
        for field in ('X', 'Y', 'Z', 'INTENSITY'):
            minKey = 'point_' + field + '_min'
            maxKey = 'point_' + field + '_max'
            minVal = points[field].min()
            maxVal = points[field].max()
            if minKey not in rangeDict or minVal < rangeDict[minKey]:
                rangeDict[minKey] = minVal
            if maxKey not in rangeDict or maxVal > rangeDict[maxKey]:
                rangeDict[maxKey] = maxVal
            
    if waveformInfo is not None and waveformInfo.size > 0:
        for field in ('RANGE_TO_WAVEFORM_START',):
            minKey = 'winfo_' + field + '_min'
            maxKey = 'winfo_' + field + '_max'
            minVal = waveformInfo[field].min()
            maxVal = waveformInfo[field].max()
            if minKey not in rangeDict or minVal < rangeDict[minKey]:
                rangeDict[minKey] = minVal
            if maxKey not in rangeDict or maxVal > rangeDict[maxKey]:
                rangeDict[maxKey] = maxVal

def setOutputScaling(rangeDict, output):
    """
    Set the scaling on the output SPD V4 file using info gathered
    by rangeFunc.
    """
    for key in rangeDict.keys():
        # process all the _min ones and assume there is a matching
        # _max
        if key.endswith('_min'):
            if key.startswith('pulse_'):
                field = key[6:-4]
                minVal = rangeDict[key]
                maxVal = rangeDict['pulse_' + field + '_max']
                
                gain = MAX_UINT16 / (maxVal - minVal)
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_PULSES, gain, minVal)
            elif key.startswith('point_'):
                field = key[6:-4]
                minVal = rangeDict[key]
                maxVal = rangeDict['point_' + field + '_max']
                                                                
                gain = MAX_UINT16 / (maxVal - minVal)
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_POINTS, gain, minVal)
            elif key.startswith('winfo_'):
                field = key[6:-4]
                minVal = rangeDict[key]
                maxVal = rangeDict['winfo_' + field + '_max']
                                                                
                gain = MAX_UINT16 / (maxVal - minVal)
                output.setScaling(field, lidarprocessor.ARRAY_TYPE_WAVEFORMS, gain, minVal)

def transFunc(data, rangeDict):
    """
    Called from pylidar. Does the actual conversion to SPD V4
    """
    pulses = data.input1.getPulses()
    points = data.input1.getPointsByPulse()
    waveformInfo = data.input1.getWaveformInfo()
    revc = data.input1.getReceived()
    
    #if points is not None:
    #    data.output1.translateFieldNames(data.input1, points, 
    #        lidarprocessor.ARRAY_TYPE_POINTS)
    #if pulses is not None:
    #    data.output1.translateFieldNames(data.input1, pulses, 
    #        lidarprocessor.ARRAY_TYPE_PULSES)
            
    # set scaling
    if data.info.isFirstBlock():
        setOutputScaling(rangeDict, data.output1)

    data.output1.setPoints(points)
    data.output1.setPulses(pulses)
    if waveformInfo is not None and waveformInfo.size > 0:
        data.output1.setWaveformInfo(waveformInfo)
    if revc is not None and revc.size > 0:
        data.output1.setReceived(revc)

def doTranslation(spatial, binSize, las, spd):
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
    if spatial:
        dataFiles.input1.setLiDARDriverOption('BIN_SIZE', float(binSize))

    controls = lidarprocessor.Controls()
    progress = cuiprogress.GDALProgressBar()
    controls.setProgress(progress)
    controls.setSpatialProcessing(spatial)
    
    # now read through the file and get the range of values for fields 
    # that need scaling.
    print('Determining range of input data...')

    import pickle    
    rangeDict = {}
    #fh = open('range.dat', 'rb')
    #rangeDict = pickle.load(fh)
    #fh.close()
    lidarprocessor.doProcessing(rangeFunc, dataFiles, controls=controls, 
                    otherArgs=rangeDict)
    fh = open('range.dat', 'wb')
    pickle.dump(rangeDict, fh)
    fh.close()

    print('Coverting to SPD V4...')
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
    
    doTranslation(spatial, cmdargs.binSize, cmdargs.las, cmdargs.spd)
    