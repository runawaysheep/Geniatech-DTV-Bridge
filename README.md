# Geniatech-DTV-Bridge

## Overview
It's a UNOFFICIAL support tool for Geniatech SmartViewTV-SVT101.
This program can receive broadcast data from the device and It has a built-in HTTP server.
You can play TV programs with a player that can play network streams.
And with the help of FFmpeg, it can be connected to TVHeadend.


## Requirement
 - Geniatech SmartViewTV-SVT101 (Multiple devices can simultaneous viewing. but maybe buggy yet.)
 - Devices(PC or Router, etc..) with Python3 installed(tested on v3.8).

 - Python Packages   
   urllib3 (1.25.9+)   
   requests (2.23.0+)   
   python-daemon (2.2.4+) (for Linux)   

  #### How to install all packages.   
   ```
   pip3 install -r requirements.txt   
   ```


## Find devices and get IP

Use official app.   
https://play.google.com/store/apps/details?id=com.nasys.smartviewtv



## Configuration
Modify 'default.json' file.
```
{
        "ip" : ["192.168.10.11", "192.168.10.12"],   ==> IP addresses of Geniatech SmartViewTV-SVT101 devices.
                                                         If you have multiple devices, enter the IP of all devices for concurrent viewing support. (separated by comma)

        "log" : "debug",                             ==> Program log level. (debug, info, error, notset)
        "fileLog" : true,                            ==> Save log to file. (Save inside 'logs' directory)

        "mode" : "server",                           ==> Working mode. (server, rec, rpc)
                                                           server : HTTP server that carries the broadcast stream.
                                                           rec : Record the broadcast stream.
                                                           rpc : Receive information about the device.
        "port" : 30012,                              ==> Port of HTTP server.

        "profile" : "fhd",                           ==> Codec for the broadcast stream. (Transcoding profile)
                                                           pass : passthrough (stream copy)
                                                           fhd : H264 1080p, AC3
                                                           hd : H264 720p, AC3
                                                           sd : H264 540p, AC3
                                                           fhd_aac : H264 1080p, AAC
                                                           hd_aac : H264 720p, AAC
                                                           sd_aac : H264 540p, AAC
        "bitRate" : 0,                               ==> Bitrate for the broadcast stream. (0 is auto)

        "bandWidth" : 6,                             ==> Band width for the broadcast stream.
        "mtype" : "8vsb",                            ==> (Just keep it as it is. I don't know if support something else like QAM.)

        "forceDeviceChange" : true                   ==> If all devices are in use, can force the device to disconnect while it is playing.
                                                         It is also useful if the connection is maintained due to program bugs.
}
```

## Execute Arguments
  Some options can be skipped if set in 'default.json' file.
  ```
  -h, --help           show this help message and exit
  -v, --version        show program's version number and exit

  -i, --ip             IP addresses of Geniatech SmartViewTV-SVT101 devices.
  -l, --log            Program log level. (debug, info, error, notset)
  --filelog            Save log to file. (Save inside 'logs' directory)
  -m, --mode           Working mode (server, rpc, rec)
  --port               Port of HTTP server.
  --profile            Transcoding profile (pass, fhd, hd, sd, fhd_aac, hd_aac, sd_aac)
  --bitRate            Transcoding bitrate (bps, 0: use auto)
  --bandWidth          Band width for the broadcast stream. (Mhz)
  --mtype              Stream mtype (8vsb, ...)
  -F, --Force          Force device change.

  -d, --daemon         Start daemon (for server only)
  -f, --freq           Stream frequency (Mhz, for rec only)
  -s, --serviceid      Stream service id (for rec only)
  -p, --pids           Stream pid list (separated by comma, for rec only)
  ```



## How to scan channels.
  There is still a little problem.   
  It's recommended to scan with other programs as much as possible.   
  In the current version, scan results are not used directly by the program.

  ```
  python scan.py --ip [Device IP] --bandWidth [bandWidth] --mtype [mtype]
  ```
  or
  ```
  python scan.py --ip [Device IP] (in this case, bandWidth:6 (Mhz), mtype:8vsb)
  ```


  Wait patiently.   
  When finished, 'channels.json' file and 'channels.m3u' file is created.   
  'channels.json' file is not used by programs. It can probably be used in the next version.   
  'channels.m3u' file is useful for use in media player. But it will have to be modified.(IP address, etc.)   



## How to run HTTP Server
  ```
  python genidtv.py --ip [Device IP] --mode server --port [Server port] --bandWidth [bandWidth] --mtype [mtype]
  ```

  If 'default.json' file is set properly.   
  Just run: python genidtv.py   
   
  This mode shuts down the program when the terminal is closed. To run in daemon mode, do the following:   
  ```
  python denidtv.py --daemon start
  ```
  
  If you want to stop, or check the status, do the following:   
  ```
  python denidtv.py -d stop
  python denidtv.py -d status
  ```
  
  In media player...   
  Open network stream, and input the following:
  ```
  http://[ip]:[port]?freq=[freq]&serviceId=[serviceId]&pids=[pids]&profile=[profile]
  ```
  ```
  ex1) IP address : 192.168.1.1
       Port : 30012
       Freq : 111 (Mhz)
       Service Id : 222
       PID list : 333,444,555
       Profile : use default.json
     => http://192.168.1.1:30012?freq=111&serviceId=222&pids=333,444,555
  ```
  ```
  ex2) IP address : 192.168.1.1
       Port : 30012
       Freq : 666 (Mhz)
       Service Id : 777
       PID list : 888,999
       Profile : fhd
     => http://192.168.1.1:30012?freq=666&serviceId=777&pids=888,999&profile=fhd
  ```


## How to record
  The built-in recording function is poor.

  ```
  python genidtv.py --mode rec --freq [frequency] --serviceId [serviceId] --pids [pids]
  ```

  Record until Ctrl+C is pressed.



## How to get device info.
  ```
  python genidtv.py --mode rpc [Command]
  ```
  Command List   
  GetFeatures / GetName / GetNetworkConfiguration / GetSignalStatus / GetTranscodingProfiles / GetUsers / GetVersion



## How to connect with TVHeadend.

1. Install FFmpeg.   
2. Start HTTP Server with debug log level. (not daemon)   
   
3. Configuration->DVB Inputs->Networks->Add   
    Type: IPTV Automatic Network   
    Network name : [Whatever you want]   
    Maximum # input streams: [Input your devices count]   
    And leave others, press 'Create'   
   
4. Configuration->DVB Inputs->Muxes->Add   
    Network: [Choose what you entered above]   
    URL: pipe://[ffmpeg path] -loglevel fatal -i [url] -vcodec copy -acodec copy -fflags nobuffer -f mpegts -tune zerolatency pipe:1   
       ex) FFmpeg path : /bin/ffmpeg   
           Url : http://192.168.1.1:30012?freq=111&serviceId=222&pids=333,444,555&profile=pass   
         => pipe:///bin/ffmpeg -loglevel fatal -i http://192.168.1.1:30012?freq=111&serviceId=222&pids=333,444,555&profile=pass -vcodec copy -acodec copy -fflags nobuffer -f mpegts -tune zerolatency pipe:1   
       - Don't enter any quotes by mistake. There are no quotes here.   
       - AAC profiles(fhd_aac, hd_aac, sd_aac) is not compatible with TVHeadend.   
    And leave others, press 'Create'   
   
5. TVHeadend checks if stream is correct.   
   Check the program log. You will see '...start transfer..'.   
   Wait a little while, the scan result of TVHeadend will show 'OK'.   
   But wait until you check the log '- conn disconnected'.   
   If you don't wait, sometimes the scan result will appear as 'FAIL'.   
   
6. Repeat 4 and 5 for the channels you want to add.   
   
7. Configuration->Channel/EPG->Channels->Add   
   ... from here, it is the same as other environments.   
