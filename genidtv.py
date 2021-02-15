import os
import sys
import io
import shutil
import argparse
import time
import requests
import json
import socket
import urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import logging
import logging.handlers
try:
	import daemon
	import daemon.pidfile
except ImportError:
	daemon = None



logger = logging.getLogger("Log")
logger.setLevel(logging.NOTSET)

pidPath = '/var/run/genidtv.pid'

programName = 'Geniatech DTV Bridge'
versionInfo = 'v0.1a'

endFlag = False

devices = []

args = None


def connect(device, freq, serviceId, profile, bitRate, bandWidth, mtype):	# freq : Mhz, bandWidth : Mhz, bitRate : bps
	device.streamId = 0
	device.sessionId = ""

	device.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	device.conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1880000)
	device.conn.connect((device.ip, 80))

	transcodingParams = None
	useAac = False

	if profile != None:
		profile = profile.lower()

		if 'aac' in profile:
			useAac = True

		if '1080' in profile or 'fhd' in profile:
			profile = "hd_h264_1080p"
		elif '720' in profile or 'hd' in profile:
			profile = "hd_h264_720p"
		elif '540' in profile or 'sd' in profile:
			profile = "sd_h264_540p"
		else:
			profile = None

	if profile == None:
		transcodingParams = {"ServiceId": serviceId}
	else:
		transcodingParams = {
			"AudioOnly": 0,
			"BitRate": bitRate,
			"HttpLiveStreaming": 0,
			"IsH264": 0,
			"IsHd": 1,
			"ProfileName": profile,
			"ServiceId": serviceId,
		}

	if useAac:
		transcodingParams['AudioToFormat'] = 'AAC'


	transcodingParamsJson = json.dumps(transcodingParams,indent=0,sort_keys=True).replace('\r','').replace('\n','')

	logger.debug('D%d : transcodingParams=%s', device.idx, transcodingParamsJson)

	cmd = 'GET http://' + device.ip + ':80/?&freq='+str(freq)+'&bw='+str(bandWidth)+'&msys=atsc&mtype='+mtype+'&wait=0 HTTP/1.1\r\nConnection:Close\r\ntranscoding-params:'+transcodingParamsJson+'\r\n\r\n'
	device.conn.sendall(cmd.encode())
	data = device.conn.recv(1024)
	logger.debug('D%d : %s', device.idx, data)

	try:
		for line in data.decode().splitlines():
			tmp = line.split(':')
			if len(tmp) > 1 :
				k = tmp[0].strip()
				v = tmp[1].strip()
				if k == "com.elgato.streamID":
					device.streamId = int(v)
				elif k == "Session":
					device.sessionId = v
	except:
		return False

	if device.streamId == 0: return False

	ret = rpc(device, 'SetUser', {'SessionId':device.sessionId,'userName':'' })

	if '"error"' in ret.text:
		return False

	logger.debug("D%d : Connect info : %d, %s", device.idx, device.streamId, device.sessionId)

	return True



def rpc(device, method, params = None):
	logger.debug('D%d : jsonrpc:%s', device.idx, method)

	headers = {'Content-Type': 'application/json'}
	data = {
		'id':device.rpcIdx,
		'jsonrpc':'2.0',
		'method':'Tombea.' + method
	}
	if params != None:
		data['params'] = params
	device.rpcIdx += 1

	jsonData =  json.dumps(data,indent=0,sort_keys=True).replace('\r','').replace('\n','')
	logger.debug('D%d : senddata : %s', device.idx, jsonData)

	return requests.post('http://'+device.ip+':80/jsonrpc', data=jsonData, headers=headers)



def req(device, qs):
	s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.connect((device.ip,554))
	cmd = 'PLAY rtsp://'+device.ip+':554/'+qs+' RTSP/1.0\r\nCSeq:'+str(device.cseq)+'\r\nSession:'+device.sessionId+'\r\n\r\n'
	s.sendall(cmd.encode())
	device.cseq += 1
	recst=s.recv(4096)
	data = recst.decode()

	if 'RTSP/1.0 200 OK' in data:
		logger.debug('D%d : rtsp req ok. qs=%s', device.idx, qs)
		return True

	logger.debug('D%d : rtsp req failed. qs=%s, data=%s', device.idx, qs, data)
	return False



def reqPids(device, pids = None):
	if pids == None:
		pids = "none"
	elif pids == "":
		pids = "0,8187"
	else:
		pids = "0," + pids + ",8187"

	return req(device, "stream=" + str(device.streamId) + "?pids=" + pids)



def disconnect(device, waitCount = 0):
	global endFlag

	if device.conn == None: return

	device.state = 0

	if waitCount > 0:
		logger.debug('D%d : - wait disconnect', device.idx)

		for i in range(waitCount * 10): # 0.1sec * 10 * waitCount = waitCount sec
			if device.usingStreamCount != 0:
				logger.debug('D%d : - disconnect canceled.(1)', device.idx)
				return # cancel
			if endFlag: return
			time.sleep(0.1) # wait 0.1sec

	if endFlag: return

	if device.usingStreamCount != 0:
		logger.debug('D%d : - disconnect canceled.(2)', device.idx)
		return # cancel

	if device.conn == None:
		logger.debug('D%d : - disconnected already', device.idx)
		return

	logger.debug('D%d : - conn disconnecting..', device.idx)

	if device.conn != None:
		device.conn.close()
		device.conn = None

	device.sessionId = ""
	device.streamId = 0

	logger.debug('D%d : - conn disconnected.', device.idx)





def startRec(filePath, freq, serviceId, pids, profile, bitRate, bandWidth, mtype):
	device = findAvailableDevice(freq, serviceId, pids, profile)
	if device == None:
		logger.debug('No available devices.')
		return

	ret = startTransfer(device, freq, serviceId, pids, profile, bitRate, bandWidth, mtype)

	if not ret:
		logger.debug('D%d : startTransfer failed.', device.idx)
		return

	buffer = bytearray(b' ' * 1880000)

	with open(filePath,'wb') as f:
		while(True):
			length = device.conn.recv_into(buffer)
			subBuffer = buffer[:length]
			f.write(subBuffer)





def startTransfer(device, freq, serviceId, pids, profile, bitRate, bandWidth, mtype):
	logger.debug('################# startTransfer')

	if device.conn != None:
		if device.freq == freq \
			and device.serviceId == serviceId \
			and device.pids == pids \
			and device.profile == profile \
			and device.bitRate == bitRate \
			and device.bandWidth == bandWidth \
			and device.mtype == mtype :
			logger.debug('D%d : same request: passthough data', device.idx)
			return True

		
		if device.conn != None:
			device.sessionId = ""
			device.usingStreamCount = 0
			disconnect(device, 0)


	ret = connect(device, freq, serviceId, profile, bitRate, bandWidth, mtype)
	if not ret: return False

	device.freq = freq
	device.serviceId = serviceId
	device.pids = pids
	device.profile = profile
	device.bitRate = bitRate
	device.bandWidth = bandWidth
	device.mtype = mtype

	ret = reqPids(device, pids) # playRequest
	if not ret: return False


	logger.info('D%d : Start!', device.idx)

	return True




class RequestHandler(SimpleHTTPRequestHandler):
	def log_message(self, format, *args):
		return

	def isBan(self):
		return os.path.isfile('ban/' + self.client_address[0])

	def do_GET(self):
		global args

		if self.isBan():
			logger.debug("ban ip. ip={ip}, path={path}".format(ip=self.client_address[0], path=self.path))
			self.send_response(403)
			self.send_header('Content-type', 'text/html')
			self.end_headers()
			self.wfile.write('<html><body>Forbidden</body></html>')
			return

		status = 200


		logger.info('# incomming ip=%s, path=%s', self.client_address[0], self.path)

		logger.debug("request headers=%s", self.headers)

		parts = urllib.parse.urlparse(self.path)
		qs = urllib.parse.parse_qs(parts.query)

		logger.debug("request path parts=%s", parts)


		freq = None
		serviceId = None
		pids = None
		profile = None
		bitRate = 0
		bandWidth = 6
		mtype = '8vsb'

		if 'freq' in qs:			freq = float(qs['freq'][0])
		if 'serviceId' in qs:		serviceId = int(qs['serviceId'][0])
		if 'pids' in qs:			pids = qs['pids'][0]
		if 'profile' in qs:			profile = qs['profile'][0]
		if 'bitRate' in qs:			bitRate = (qs['bitRate'][0])
		if 'bandWidth' in qs:		bandWidth = (qs['bandWidth'][0])
		if 'mtype' in qs:			mtype = qs['mtype'][0]

		if profile == None : profile = args.profile
		if bitRate == None : bitRate = args.bitRate
		if bandWidth == None : bandWidth = args.bandWidth
		if mtype == None : mtype = args.mtype

		ret = False
		device = None

		if freq != None and serviceId != None and pids != None:
			for i in range(3):
				device = findAvailableDevice(freq, serviceId, pids, profile)
				if device == None:
					logger.debug('No available devices. try=%d', i+1)
					time.sleep(0.5)
				else:
					break

		if device == None and args.forceDeviceChange:
			device = devices[0]


		if device != None:
			logger.debug('D%d : Device IP=%s', device.idx, device.ip)
			ret = startTransfer(device, freq, serviceId, pids, profile, bitRate, bandWidth, mtype)
			if ret == False:
				disconnect(device)

		if device == None or device != None and device.conn == None:
			status = 404

		contentType = 'text/html'

		send_headers = {}

		if status == 200:
			contentType = 'video/mp4'
			send_headers['Access-Control-Allow-Origin'] = '*'

		self.send_response(status)
		self.send_header('Content-type', contentType)
		for key in send_headers.keys():
			self.send_header(key, send_headers[key])
		self.end_headers()

		logger.debug('D%d : status==%d', device.idx, status)

		if status == 200:
			logger.debug('D%d : Start stream.', device.idx)

			device.usingStreamCount += 1
			try:
				buffer = bytearray(b' ' * 188000)
				while(True):
					if device.sessionId == "": break
					length = device.conn.recv_into(buffer)
					self.wfile.write(buffer[:length])

			except Exception as ex:
				logger.debug('D%d : %s', device.idx, ex)
			finally:
				device.state = 0
				device.usingStreamCount -= 1

				if device.usingStreamCount <= 0:
					logger.info('D%d : Stream finished.', device.idx)
					disconnect(device, 2)

		else:
			self.wfile.write(b'error')


class TVDevice:
	idx : int
	ip : str
	conn : socket = None
	sessionId : str = ''
	streamId : int = 0
	usingStreamCount : int = 0
	state : int = 0
	rpcIdx : int = 1
	cseq : int = 1001

	freq : float
	serviceId : int
	pids : str
	profile : str
	bitRate : int
	bandWidth : float
	mtype : str



def findAvailableDevice(freq, serviceId, pids, profile):
	ret = None
	for device in devices:
		if device.conn != None and device.freq == freq and device.serviceId == serviceId and device.pids == pids and device.profile == profile:
			ret = device
			break

	for device in devices:
		if device.state == 0:
			ret = device
			break

	if ret == None:
		return ret

	ret.state = 1

	return ret




def initDevices(ipList):
	global devices

	if not isinstance(ipList, list):
		ipList = [ipList]

	idx = 1
	for ip in ipList:
		device = TVDevice()
		device.idx = idx
		device.ip = ip

		devices.append(device)
		idx += 1



def startServer(isDaemon = False):
	global args

	if not isDaemon:
		pid = doDaemonAction('isRunning')
		if pid != None:
			print('Running already (pid: %d)' % pid)
			sys.exit(1)

	port = args.port
	httpd = ThreadingHTTPServer(("", port), RequestHandler)
	logger.info("serving at port : %d", port)

	try :
		if not isDaemon:
			with open(pidPath, "w") as f:
				f.write("%d" % os.getpid())

		httpd.serve_forever()
	except KeyboardInterrupt:
		logger.debug("interrupted")
	finally:
		if not isDaemon:
			os.remove(pidPath)




def doDaemonAction(action, logfile_fileno = None):
	if daemon == None:
		return

	pidLockfile = daemon.pidfile.PIDLockFile(pidPath)

	if action == 'start':
		if pidLockfile.is_locked():
			print("Running already (pid: %d)" % pidLockfile.read_pid())
			exit(1)

		print('Start daemon.')

		context = daemon.DaemonContext(pidfile=pidLockfile)

		if logfile_fileno != None:
			context.files_preserve = [logfile_fileno]

		with context:
			startServer(True)

	elif action == 'stop':
		if pidLockfile.is_locked():
			cmd = 'kill '+ str(pidLockfile.read_pid())
			os.system(cmd)
			try:
				os.remove(pidPath)
			except:
				pass
			print('Stop daemon.')

	elif action == 'status':
		if pidLockfile.is_locked():
			print('Running. (pid: %d)' % pidLockfile.read_pid())
		else:
			print('Terminated.')

	elif action == 'isRunning':
		if pidLockfile.is_locked():
			return pidLockfile.read_pid()




def get_arg_parser():
	parser = argparse.ArgumentParser(description=programName, formatter_class=argparse.RawTextHelpFormatter)
	parser.add_argument('target', default=None, type=str, nargs='?', help='RPC : Method, Rec : save file path')
	parser.add_argument('-v','--version',action='version', version=programName + ' ' + versionInfo)

	parser.add_argument('-i','--ip',dest='ip',default=None, type=str, help='Device IP')
	parser.add_argument('-l','--log',dest='log',default=None, type=str, help='Log Level (debug, info, error, notset)')
	parser.add_argument('--filelog',dest='fileLog',action='store_true', help='Use File Log')
	parser.add_argument('-m','--mode',dest='mode', default='server', type=str, help='Working mode (server, rpc, rec)')
	parser.add_argument('--port', dest='port', default=None, type=int, help='Server port')
	parser.add_argument('--profile',dest='profile',default=None, type=str, help='Transcoding profile (fhd, hd, sd, pass)')
	parser.add_argument('--bitRate',dest='bitRate',default=None, type=int, help='Transcoding bit rate (bps, 0: use auto)')
	parser.add_argument('--bandWidth',dest='bandWidth',default=None, type=float, help='Stream band width')
	parser.add_argument('--mtype',dest='mtype',default=None, type=str, help='Stream mtype (8vsb, ...)')
	parser.add_argument('-F','--Force',dest='forceDeviceChange',default=None, type=float, help='Force device change.')

	parser.add_argument('-d','--daemon',dest='daemon',action='store_true', help='Start daemon (for server only)')
	parser.add_argument('-f','--freq',dest='freq',default=None, type=float, help='Stream frequency (for rec only)')
	parser.add_argument('-s','--serviceid',dest='serviceId',default=None, type=int, help='Stream service id (for rec only)')
	parser.add_argument('-p','--pids',dest='pids',default=None, type=str, help='Stream pid list (for rec only)')

	return parser




def main():
	global endFlag
	global args
	global devices

	parser = get_arg_parser()
	args = parser.parse_args()

	defaultArgs = {}
	try:
		with open('default.json') as jsonFile:
			defaultArgs = json.load(jsonFile)
	except:
		pass

	if args.ip == None and "ip" in defaultArgs: args.ip = defaultArgs["ip"]

	if args.mode == None and "mode" in defaultArgs: args.mode = defaultArgs["mode"]
	if args.port == None and "port" in defaultArgs: args.port = defaultArgs["port"]

	if args.profile == None and "profile" in defaultArgs: args.profile = defaultArgs["profile"]
	if args.bitRate == None and "bitRate" in defaultArgs: args.bitRate = defaultArgs["bitRate"]
	if args.bandWidth == None and "bandWidth" in defaultArgs: args.bandWidth = defaultArgs["bandWidth"]
	if args.mtype == None and "mtype" in defaultArgs: args.mtype = defaultArgs["mtype"]

	if args.log == None and "log" in defaultArgs: args.log = defaultArgs["log"]
	if args.fileLog == False and "fileLog" in defaultArgs: args.fileLog = defaultArgs["fileLog"]

	if args.forceDeviceChange == None and "forceDeviceChange" in defaultArgs: args.forceDeviceChange = defaultArgs["forceDeviceChange"]

	logfile_fileno = None

	if args.log != None:
		handler_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
		
		args.log = args.log.lower()
		
		if args.log == 'debug':
			logger.setLevel(logging.DEBUG)
		elif args.log == 'info':
			logger.setLevel(logging.INFO)
		elif args.log == 'warning':
			logger.setLevel(logging.WARNING)
		elif args.log == 'error':
			logger.setLevel(logging.ERROR)
		elif args.log == 'critical':
			logger.setLevel(logging.CRITICAL)
		else:
			logger.setLevel(logging.NOTSET)

		stream_handler = logging.StreamHandler()
		stream_handler.setFormatter(handler_format)

		logger.addHandler(stream_handler)

		if args.fileLog:
			logDir = os.path.join(os.path.dirname(os.path.realpath(__file__)),'logs')
			if not os.path.exists(logDir):
				os.makedirs(logDir)

			print('logging on file : %s' % logDir)

			file_handler = logging.handlers.TimedRotatingFileHandler(filename=os.path.join(logDir,'log'),
								when='midnight',
								interval=1,
								utc=False,
								encoding='utf-8')
			file_handler.suffix = "%Y-%m-%d"
			file_handler.setFormatter(handler_format)
			logfile_fileno = file_handler.stream.fileno()

			logger.addHandler(file_handler)


	print(programName + " " + versionInfo)

	initDevices (args.ip)

	if len(devices) == 0:
		print('Option [-i,--ip] is required.')
		sys.exit(1)


	if args.mode == 'server':
		if args.daemon:
			if daemon == None:
				print('python-daemon is not installed or not available in this system.')
				sys.exit(1)

			action = args.target
			if action == None: action = 'start'

			if action == 'start' or action == 'stop' or action == 'status':
				doDaemonAction(action, logfile_fileno)
			elif action == 'stop':
				doDaemonAction('stop')
			else:
				print('Unknown daemon option :', action)

		else:
			startServer()

	elif args.mode == 'rpc':
		if args.target == None:
			print('Rpc name is required. (GetFeatures / GetName / GetNetworkConfiguration / GetSignalStatus / GetTranscodingProfiles / GetUsers / GetVersion)')
			return

		try:
			device = findAvailableDevice(None, None, None, None)
			if device == None:
				logger.info('No available devices.')
				sys.exit(1)

			ret = rpc(device, args.target)
			logger.info(ret.text)
		except Exception as ex:
			logger.error(ex)
			sys.exit(1)

	elif args.mode == 'rec':
		filePath = args.target
		if filePath == None:
			print('Save file name is required.')
			sys.exit(1)

		if args.freq == None:
			print('Option [-f,--freq] is required.')
			sys.exit(1)

		if args.serviceId == None:
			print('Option [-s,--serviceId] is required.')
			sys.exit(1)

		if args.pids == None:
			print('Option [-p,--pids] is required.')
			sys.exit(1)


		startRec(filePath, args.freq, args.serviceId, args.pids, args.profile, args.bitRate, args.bandWidth, args.mtype)

	else:
		print('Invalid Mode.')
		sys.exit(1)

	endFlag = True
	sys.exit(0)





if __name__ == "__main__" :
	main()

