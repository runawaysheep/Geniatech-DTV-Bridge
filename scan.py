import requests
import json
import socket
import time
import urllib.parse
import os
import sys
import io
import argparse
import errno
import traceback

endFlag = False

idx = 1
cseq = 1001

conn = None
sessionId = ""
streamId = 0

args = None

programName = 'Geniatech DTV Channel Scanner'
versionInfo = 'v0.1a'

def connect(freq, bandWidth, mtype):	# freq : Mhz, bandWidth : Mhz, bitRate : bps
	global streamId
	global sessionId
	global args
	global conn

	streamId = 0
	sessionId = ""

	conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024000)
	conn.connect((args.ip, 80))

	transcodingParams = {"ServiceId": 0}

	transcodingParamsJson = json.dumps(transcodingParams,indent=0,sort_keys=True).replace('\r','').replace('\n','')

	cmd = 'GET http://' + args.ip + ':80/?&freq='+str(freq)+'&bw='+str(bandWidth)+'&msys=atsc&mtype='+mtype+'&wait=0 HTTP/1.1\r\nConnection:Close\r\ntranscoding-params:'+transcodingParamsJson+'\r\n\r\n'
	conn.sendall(cmd.encode())
	data = conn.recv(1024)

	try:
		for line in data.decode().splitlines():
			tmp = line.split(':')
			if len(tmp) > 1 :
				k = tmp[0].strip()
				v = tmp[1].strip()
				if k == "com.elgato.streamID":
					streamId = int(v)
				elif k == "Session":
					sessionId = v
	except:
		return False

	if streamId == 0: return False

	ret = rpc('SetUser', {'SessionId':sessionId,'userName':'' })

	if '"error"' in ret.text:
		return False

	print("Connect info : " + str(streamId) + ", " + sessionId)

	return True


def rpc(method, params = None):
	global idx
	global args

	print('jsonrpc:' + method)

	headers = {'Content-Type': 'application/json'}
	data = {
		'id':idx,
		'jsonrpc':'2.0',
		'method':'Tombea.' + method
	}
	if params != None:
		data['params'] = params
	idx = idx + 1

	jsonData =  json.dumps(data,indent=0,sort_keys=True).replace('\r','').replace('\n','')
	print('senddata : ' + jsonData)

	return requests.post('http://'+args.ip+':80/jsonrpc', data=jsonData, headers=headers)


def req(qs):
	global args
	global cseq
	global sessionId

	s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.connect((args.ip,554))
	cmd = 'PLAY rtsp://'+args.ip+':554/'+qs+' RTSP/1.0\r\nCSeq:'+str(cseq)+'\r\nSession:'+sessionId+'\r\n\r\n'
	s.sendall(cmd.encode())
	cseq = cseq + 1
	recst=s.recv(4096)
	data = recst.decode()

	if 'RTSP/1.0 200 OK' in data:
		print('rtsp req ok. qs='+ qs)
		return True

	print('rtsp req failed. qs='+ qs + ', data='+ data)
	return False



def reqPids(pids = None):
	global streamId

	if pids == None:
		pids = "none"
	elif pids == "":
		pids = "0,8187"
	else:
		pids = "0," + pids + ",8187"

	return req("stream=" + str(streamId) + "?pids=" + pids)


def disconnect(waitCount = 0):
	global conn
	global sessionId
	global endFlag

	if conn == None: return

	if waitCount > 0:
		print ('----------wait disconnect')

		for i in range(waitCount * 10): # 0.1sec * 10 * waitCount = waitCount sec
			if endFlag: return
			time.sleep(0.1) # wait 0.1sec

	if endFlag: return

	if conn == None:
		print ('----------disconnected already')
		return

	print ('----------conn disconnecting..')

	if conn != None:
		conn.close()
		conn = None

	sessionId = ""
	streamId = 0

	print ('----------conn disconnected.')



def parseTvct(buffer, arrSize, isMptsFound, mptsPids, mptsServiceIds):
	tvctPos = 15
	channelInVctLength = 0

	pids = [0] * 4
	isVideo = False
	isVideoPid = False
	isAudioPid = False

	chNumMajor = None
	chNumMinor = None
	chName = None

	result = []

	print("isMptsFound=",isMptsFound)

	if isMptsFound:
		numChannelsInSection = buffer[14]
		correctMptsChannel = 0
		
		for i in range(numChannelsInSection):
			try:
				descriptorLen = (0x3 & buffer[tvctPos + 30]) << 8 | buffer[tvctPos + 31]
				channelInVctLength = 32 + descriptorLen

				for j in range(tvctPos, tvctPos + channelInVctLength):
					if buffer[j] != 161: continue
					noEl = buffer[j + 4]

					if noEl > 1 and j + 6 * noEl <= tvctPos + channelInVctLength:
						for k in range(j + 4, j + 6 * noEl):
							if buffer[k] == 2 and not isVideo:
								pcrPid = (buffer[j + 2] & 0x1F) << 8 | buffer[j + 3]
								videoPid = (buffer[k + 1] & 0x1F) << 8 | buffer[k + 2]
								pids[1] = pcrPid
								pids[2] = videoPid
								isVideoPid = True
								isVideo = True
							elif buffer[k] == 129 and not isAudioPid:
								audioPid = (buffer[k + 1] & 0x1F) << 8 | buffer[k + 2]
								pids[3] = audioPid
								isAudioPid = True
								isVideo = True

					if isVideo and isVideoPid and isAudioPid:
						isAudioPid = False
						break

				tvctPos += channelInVctLength

				if isVideo:
					chNamePos = tvctPos - channelInVctLength

					chNumMajor = (buffer[chNamePos + 14] & 0xf) << 8 | buffer[chNamePos + 15] >> 2
					chNumMinor = (buffer[chNamePos + 15] & 0x3) << 8 | (buffer[chNamePos + 16] & 0xff)

					chNameBytes = buffer[chNamePos : chNamePos + 14]
					try:
						chName = chNameBytes.decode('utf-16-be')
					except:
						continue

					zeroIdx = chName.find(chr(0))
					if zeroIdx >= 0: chName = chName[:zeroIdx]

					if chNumMajor > 192: chNumMajor -= 192

					pids[0] = mptsPids[i]

					result.append({
						"chNumMajor" : chNumMajor,
						"chNumMinor" : chNumMinor,
						"chName" : chName,
						"serviceId" : mptsServiceIds[i],
						"pids" : pids[:]
					})
					isVideo = False

			except Exception as ex:
				isVideo = False
				traceback.print_exc()
	else:
		descriptorLen = (0x3 & buffer[45]) << 8 | buffer[46]
		for i in range(len(buffer)):
			if buffer[i] != 161: continue

			noEl = buffer[i + 4]
			if noEl > 1:
				for j in range(i+4, i + 6 * noEl):
					if buffer[j] == 2:
						pcrPid = (buffer[i + 2] & 0x1F) << 8 | buffer[i + 3]
						videoPid = (buffer[j + 1] & 0x1F) << 8 | buffer[j + 2]
						pids[1] = pcrPid
						pids[2] = videoPid
					elif buffer[j] == 129:
						audioPid = (buffer[j + 1] & 0x1F) << 8 | buffer[j + 2]
						pids[3] = audioPid
					break

		chNamePos = 15
		chNameBytes = buffer[chNamePos : chNamePos + 14]
		try:
			chName = chNameBytes.decode('utf-16-be')

			chNumMajor = (buffer[chNamePos + 14] & 0xf) << 8 | buffer[chNamePos + 15] >> 2
			chNumMinor = (buffer[chNamePos + 15] & 0x3) << 8 | (buffer[chNamePos + 16] & 0xff)

			zeroIdx = chName.find(chr(0))
			if zeroIdx >= 0: chName = chName[:zeroIdx]

			if chNumMajor > 192: chNumMajor -= 192

			result.append({
				"chNumMajor" : chNumMajor,
				"chNumMinor" : chNumMinor,
				"chName" : chName,
				"serviceId" : mptsServiceIds[0],
				"pids" : pids[:]
			})
		except:
			pass

	return result




def startScan(freq, bandWidth, mtype):
	print("############# freq===",freq)

	ret = reqPids(None) # noneRequest
	if not ret: return False
	time.sleep(0.1)

	ret = req("?freq=" + str(freq) + "&bw="+str(bandWidth)+"&msys=atsc&mtype="+mtype+"&wait=0") # freqRequest
	if not ret: return False
	time.sleep(0.1)

	ret = reqPids("") # allRequest
	time.sleep(2)

	buffer = bytearray(b' ' * 188000)
	bufferLen = conn.recv_into(buffer)

	isTvctFound = False
	isPatFound = False
	isMptsFound = False
	isOverTvct = False
	mptsPids = None
	mptsServiceIds = None
	serviceId = None

	isCorrent = False

	tryCount = 0

	info = None

	while(True) :
		for i in range(188*5, bufferLen, 188):
			if buffer[i] == 71:
				pid = (buffer[i+1] & 0x1f) << 8 + buffer[i+2]
				afl = buffer[i+5]

				if not isPatFound and pid == 0 and afl == 0:
					isPatFound = True
					length = (buffer[i + 6] & 0xF) * 256 + buffer[i + 7]
					length = (length - 9) // 4

					if length >= 2:
						isMptsFound = True
						if length >= 4:
							isOverTvct = True

					if isMptsFound:
						mptsPids = [0] * length
						mptsServiceIds = [0] * length
						for j in range(length):
							mptsPids[j] = (buffer[i + (15 + 4 * j)] & 0x1F & 0xFF) * 256 + (buffer[i + (16 + 4 * j)] & 0xFF)
							mptsServiceIds[j] = (buffer[i + (13 + 4 * j)] & 0xFF) * 256 + (buffer[i + (14 + 4 * j)] & 0xFF)
					else:
						pid = (buffer[i + 15] & 0x1F) * 256 + buffer[i + 16]
						serviceId = buffer[i + 13] * 256 + buffer[i + 14]
					isCorrent = True

				if isMptsFound:
					if buffer[i + 5] == 200 and not isTvctFound and isPatFound:
						arrSize = None

						b = buffer[i:i+188]
						if isOverTvct:
							arrSize = 188
						else :
							arrSize = 396
							cc = buffer[i + 3] & 0xf
							if cc == 15: cc = -1

							tmp = buffer[i:i+1316]
							for j in range(0, 1316, 188):
								if ((tmp[j + 1] & 0x1f) << 8 | (tmp[j + 2] & 0xff)) == 0x1ffb and (tmp[j + 3] & 0xf) == cc + 1:
									b2 = buffer[j + 4: j + 188]
									b = b + b2
									isOverTvct = False
									break

							isOverTvct = False

						info = parseTvct(b, arrSize, isMptsFound, mptsPids, mptsServiceIds)

						isTvctFound = True
						isCorrent = True
						if isPatFound and isTvctFound:
							break
				elif buffer[i + 5] == 200 and not isTvctFound and isPatFound:
					b = buffer[i:i+188]
					info = parseTvct(b, 188, isMptsFound, mptsPids, [serviceId])

					isTvctFound = True
					isCorrent = True

					if isPatFound and isTvctFound:
						break

			
			if not isTvctFound and not isPatFound and i >= bufferLen - 188:
				isCorrent = False
				break

		if isPatFound and isTvctFound:
			break

		if isCorrent:
			buffer = bytearray(b' ' * 188000)
			bufferLen = conn.recv_into(buffer)
		else:
			tryCount += 1
			if tryCount == 5:
				break
			bufferLen = conn.recv_into(buffer)
			continue

	if isCorrent and isMptsFound:
		for item in info:
			item['freq'] = freq
			item['bandWidth'] = bandWidth
			item['mtype'] = mtype

		print(info)
		return info
	else:
		pass




def get_arg_parser():
	parser = argparse.ArgumentParser(description=programName, formatter_class=argparse.RawTextHelpFormatter)
	parser.add_argument('-v','--version',action='version', version=programName + ' ' + versionInfo)
	parser.add_argument('-i','--ip',dest='ip',default=None, type=str, help='Device IP')

	parser.add_argument('--bandWidth',dest='bandWidth',default=None, type=float, help='')
	parser.add_argument('--mtype',dest='mtype',default=None, type=str, help='')

	return parser


def main():
	global endFlag
	global args

	parser = get_arg_parser()
	args = parser.parse_args()

	if args.ip == None:
		print("Option --ip is required.")
		sys.exit(1)

	if args.bandWidth == None: args.bandWidth = 6
	if args.mtype == None: args.mtype = '8vsb'

	allResults = []

	freqFrom = 57.0
	freqTo = 855.0

	ret = connect(0, args.bandWidth, args.mtype)

	if not ret:
		print('connect failed.')
		return

	freq = freqFrom
	while(freq <= freqTo):
		ret = startScan(freq, args.bandWidth, args.mtype)
		if ret != None:
			allResults += ret
		freq += args.bandWidth

	disconnect(0)

	allResults.sort(key=lambda x: (x['chNumMajor'], x['chNumMinor']))

	print("##############################")
	print(allResults)

	with open('channels.json', 'w', encoding='UTF-8-sig') as file:
		file.write(json.dumps(allResults, ensure_ascii=False, indent=4, sort_keys=True))

	with open('channels.m3u', 'w', encoding='UTF-8-sig') as file:
		file.write('#EXTM3U\r\n')
		for info in allResults:
			file.write(f'#EXTINF:-1, tvg-name="{info["chName"]}" tvg-chno="{info["chNumMajor"]}-{info["chNumMinor"]}",{info["chName"]}\r\n')
			file.write(f'http://127.0.0.1:30012?freq={info["freq"]}&serviceId={info["serviceId"]}&pids={",".join(str(x) for x in info["pids"])}&bandWidth={info["bandWidth"]}&mtype={info["mtype"]}\r\n')

	endFlag = True
	sys.exit(0)





if __name__ == "__main__" :
	main()

