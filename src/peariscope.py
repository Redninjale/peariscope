#!/usr/bin/env python3
#----------------------------------------------------------------------------
# Copyright (c) 2018 FIRST. All Rights Reserved.
# Open Source Software - may be modified and shared by FRC teams. The code
# must be accompanied by the FIRST BSD license file in the root directory of
# the project.
#----------------------------------------------------------------------------

import json
import time
import sys

from cscore import CameraServer, VideoSource, UsbCamera, MjpegServer
from networktables import NetworkTablesInstance, NetworkTables
import ntcore

import numpy as np
import cv2

#   JSON format:
#   {
#       "team": <team number>,
#       "ntmode": <"client" or "server", "client" if unspecified>
#       "cameras": [
#           {
#               "name": <camera name>
#               "path": <path, e.g. "/dev/video0">
#               "pixel format": <"MJPEG", "YUYV", etc>   // optional
#               "width": <video mode width>              // optional
#               "height": <video mode height>            // optional
#               "fps": <video mode fps>                  // optional
#               "brightness": <percentage brightness>    // optional
#               "white balance": <"auto", "hold", value> // optional
#               "exposure": <"auto", "hold", value>      // optional
#               "properties": [                          // optional
#                   {
#                       "name": <property name>
#                       "value": <property value>
#                   }
#               ],
#               "stream": {                              // optional
#                   "properties": [
#                       {
#                           "name": <stream property name>
#                           "value": <stream property value>
#                       }
#                   ]
#               }
#           }
#       ]
#       "switched cameras": [
#           {
#               "name": <virtual camera name>
#               "key": <network table key used for selection>
#               // if NT value is a string, it's treated as a name
#               // if NT value is a double, it's treated as an integer index
#           }
#       ]
#   }

configFile = "/boot/frc.json"

class CameraConfig: pass

team = None
server = False
cameraConfigs = []
switchedCameraConfigs = []
cameras = []
insts = []

def parseError(str):
    """Report parse error."""
    print("config error in '" + configFile + "': " + str, file=sys.stderr)

def readCameraConfig(config):
    """Read single camera configuration."""
    cam = CameraConfig()

    # name
    try:
        cam.name = config["name"]
    except KeyError:
        parseError("could not read camera name")
        return False

    # path
    try:
        cam.path = config["path"]
    except KeyError:
        parseError("camera '{}': could not read path".format(cam.name))
        return False

    # stream properties
    cam.streamConfig = config.get("stream")

    cam.config = config

    cameraConfigs.append(cam)
    return True

def readSwitchedCameraConfig(config):
    """Read single switched camera configuration."""
    cam = CameraConfig()

    # name
    try:
        cam.name = config["name"]
    except KeyError:
        parseError("could not read switched camera name")
        return False

    # path
    try:
        cam.key = config["key"]
    except KeyError:
        parseError("switched camera '{}': could not read key".format(cam.name))
        return False

    switchedCameraConfigs.append(cam)
    return True

def readConfig():
    """Read configuration file."""
    global team
    global server

    # parse file
    try:
        with open(configFile, "rt", encoding="utf-8") as f:
            j = json.load(f)
    except OSError as err:
        print("could not open '{}': {}".format(configFile, err), file=sys.stderr)
        return False

    # top level must be an object
    if not isinstance(j, dict):
        parseError("must be JSON object")
        return False

    # team number
    try:
        team = j["team"]
    except KeyError:
        parseError("could not read team number")
        return False

    # ntmode (optional)
    if "ntmode" in j:
        str = j["ntmode"]
        if str.lower() == "client":
            server = False
        elif str.lower() == "server":
            server = True
        else:
            parseError("could not understand ntmode value '{}'".format(str))

    # cameras
    try:
        cameras = j["cameras"]
    except KeyError:
        parseError("could not read cameras")
        return False
    for camera in cameras:
        if not readCameraConfig(camera):
            return False

    # switched cameras
    if "switched cameras" in j:
        for camera in j["switched cameras"]:
            if not readSwitchedCameraConfig(camera):
                return False

    return True

def startCamera(config):
    """Start running the camera."""
    print("Starting camera '{}' on {}".format(config.name, config.path))
    inst = CameraServer.getInstance()
    camera = UsbCamera(config.name, config.path)
    server = inst.startAutomaticCapture(camera=camera, return_server=True)

    camera.setConfigJson(json.dumps(config.config))
    camera.setConnectionStrategy(VideoSource.ConnectionStrategy.kKeepOpen)

    if config.streamConfig is not None:
        server.setConfigJson(json.dumps(config.streamConfig))

    return camera, inst

def startSwitchedCamera(config):
    """Start running the switched camera."""
    print("Starting switched camera '{}' on {}".format(config.name, config.key))
    server = CameraServer.getInstance().addSwitchedCamera(config.name)

    def listener(fromobj, key, value, isNew):
        if isinstance(value, float):
            i = int(value)
            if i >= 0 and i < len(cameras):
              server.setSource(cameras[i])
        elif isinstance(value, str):
            for i in range(len(cameraConfigs)):
                if value == cameraConfigs[i].name:
                    server.setSource(cameras[i])
                    break

    NetworkTablesInstance.getDefault().getEntry(config.key).addListener(
        listener,
        ntcore.constants.NT_NOTIFY_IMMEDIATE |
        ntcore.constants.NT_NOTIFY_NEW |
        ntcore.constants.NT_NOTIFY_UPDATE)

    return server

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        configFile = sys.argv[1]

    # read configuration
    if not readConfig():
        sys.exit(1)

    # start NetworkTables
    ntinst = NetworkTablesInstance.getDefault()
    if server:
        print("Setting up NetworkTables server")
        ntinst.startServer()
    else:
        print("Setting up NetworkTables client for team {}".format(team))
        ntinst.startClientTeam(team)

    # start cameras
    for config in cameraConfigs:
        camera, inst = startCamera(config)
        cameras.append(camera)
        insts.append(inst)

    # start switched cameras
    for config in switchedCameraConfigs:
        startSwitchedCamera(config)

    #
    # Peariscope Setup Code
    #

    print("Peariscope by Pearadox Robotics Team 5414")

    # Use only the first (non-switched) camera and its instance
    camera = cameras[0]
    cs = insts[0]

    print("Info", camera.getInfo())
    print("Path", camera.getPath())

    config = json.loads(camera.getConfigJson())
    height = config["height"]
    width = config["width"]
    fps = config["fps"]
    print("height {} width {} fps {}".format(height, width, fps))

    # Capture images from the camera
    cvSink = cs.getVideo()

    # Send images back to the Dashboard
    outputStream = cs.putVideo("Peariscope", width, height)

    # Preallocate space for new images
    image = np.zeros(shape=(height, width, 3), dtype=np.uint8)

    # Use network table to publish camera data
    sd = NetworkTables.getTable("Peariscope")

    current_time = time.time()
    while True:
        start_time = current_time

        # Grab a frame from the camera and put it in the source image
        frame_time, image = cvSink.grabFrame(image)

        # If there is an error then notify the output and skip the iteration
        if frame_time == 0:
            outputStream.notifyError(cvSink.getError())
            continue

        #
        # Peariscope Loop Code (process the image)
        #

        image_height, image_width = image.shape[:2]
        sd.putNumberArray("image_size", [image_height, image_width])

        # Convert the image to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Smooth (blur) the image to reduce high frequency noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        (min_val, max_val, min_loc, max_loc) = cv2.minMaxLoc(blurred)
        sd.putNumberArray("min_max_val", [min_val, max_val])

        # Threshold the image to reveal the brightest regions in the blurred image
        thresh = cv2.threshold(blurred, 225, 255, cv2.THRESH_BINARY)[1]

        # Remove any small blobs of noise using a series of erosions and dilations
        thresh = cv2.erode(thresh, None, iterations=2)
        thresh = cv2.dilate(thresh, None, iterations=4)

        # Perform a connected component analysis on the thresholded image
        connectivity = 4 # Choose 4 or 8 for connectivity type
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            thresh, connectivity, cv2.CV_32S)

        RED = (0, 0, 255)
        GRN = (0, 255, 0)
        BLU = (255, 0, 0)
        YEL = (0, 255, 255)

        # Examine each blob
        x_list = []
        y_list = []
        for i in range(num_labels):
            # Ignore this label if it is the background
            if i == 0:
                continue

            # Get features of the blob
            blob_area  = stats[i, cv2.CC_STAT_AREA]
            box_left   = stats[i, cv2.CC_STAT_LEFT]
            box_top    = stats[i, cv2.CC_STAT_TOP]
            box_width  = stats[i, cv2.CC_STAT_WIDTH]
            box_height = stats[i, cv2.CC_STAT_HEIGHT]
            box_bottom = box_top + box_height
            box_right  = box_left + box_width
            centroid_x, centroid_y = centroids[i]

            # Ignore blobs that are too big
            if box_height > image_height/2 or box_width > image_width/2:
                continue

            # Add the centroid to the list of detections
            x_list.append(centroid_x)
            y_list.append(centroid_y)

            # Draw a circle to mark the centroid of the reflector blob
            center = (int(centroid_x), int(centroid_y)) # Center of the circle
            radius = 2
            cv2.circle(image, center, radius, RED, -1)

            # Draw a rectangle to mark the bounding box of the reflector blob
            line_thickness = 2
            cv2.rectangle(image, (box_left, box_top), (box_right, box_bottom),
                          RED, line_thickness)

        # Draw crosshairs on the image
        image_center_x = int(image_width/2)
        image_center_y = int(image_height/2)
        cv2.line(image, (image_center_x, 0), (image_center_x, image_height-1), YEL, 1)
        cv2.line(image, (0, image_center_y), (image_width-1, image_center_y), YEL, 1)

        # Give the output stream a new image to display
        outputStream.putFrame(image)

        # Output the lists of x and y coordinates for the blobs
        sd.putNumberArray("x_list", x_list)
        sd.putNumberArray("y_list", y_list)

        # Compute the coordinates as percentage distances from image center
        # for x (horizontal), 0 is center,  -100 is image left, 100 is image right
        # for y (vertical), 0 is center, -100 is image top, 100 is image bottom
        x_list_pct = [(x-image_width/2)/(image_width/2)*100 for x in x_list]
        y_list_pct = [(y-image_height/2)/(image_height/2)*100 for y in y_list]
        sd.putNumberArray("x_list_pct", x_list_pct)
        sd.putNumberArray("y_list_pct", y_list_pct)

        current_time = time.time()
        elapsed_time = current_time - start_time
        sd.putNumber("elapsed_time", elapsed_time)
        sd.putNumber("fps", 1/elapsed_time)

