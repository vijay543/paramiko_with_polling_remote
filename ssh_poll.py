import paramiko
import logging
import socket
import time
import datetime
 
 
# ================================================================
# class MySSH
# ================================================================
class MySSH:
    '''
    Create an SSH connection to a server and execute commands.
    Here is a typical usage:
 
        ssh = MySSH()
        ssh.connect('host', 'user', 'password', port=22)
        if ssh.connected() is False:
            sys.exit('Connection failed')
 
        # Run a command that does not require input.
        status, output = ssh.run('uname -a')
        print 'status = %d' % (status)
        print 'output (%d):' % (len(output))
        print '%s' % (output)
 
        # Run a command that does requires input.
        status, output = ssh.run('sudo uname -a', 'sudo-password')
        print 'status = %d' % (status)
        print 'output (%d):' % (len(output))
        print '%s' % (output)
    '''
    def __init__(self, compress=True, verbose=False):
        '''
        Setup the initial verbosity level and the logger.
 
        @param compress  Enable/disable compression.
        @param verbose   Enable/disable verbose messages.
        '''
        self.ssh = None
        self.transport = None
        self.compress = compress
        self.bufsize = 65536
 
        # Setup the logger
        self.logger = logging.getLogger('MySSH')
        self.set_verbosity(verbose)
 
        fmt = '%(asctime)s MySSH:%(funcName)s:%(lineno)d %(message)s'
        format = logging.Formatter(fmt)
        handler = logging.StreamHandler()
        handler.setFormatter(format)
        self.logger.addHandler(handler)
        self.info = self.logger.info
 
    def __del__(self):
        if self.transport is not None:
            self.transport.close()
            self.transport = None
 
    def connect(self, hostname, username, password, port=22):
        '''
        Connect to the host.
 
        @param hostname  The hostname.
        @param username  The username.
        @param password  The password.
        @param port      The port (default=22).
 
        @returns True if the connection succeeded or false otherwise.
        '''
        self.info('connecting %s@%s:%d' % (username, hostname, port))
        self.hostname = hostname
        self.username = username
        self.port = port
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.ssh.connect(hostname=hostname,
                             port=port,
                             username=username,
                             password=password)
            self.transport = self.ssh.get_transport()
            self.transport.use_compression(self.compress)
            self.info('succeeded: %s@%s:%d' % (username,
                                               hostname,
                                               port))
        except socket.error as e:
            self.transport = None
            self.info('failed: %s@%s:%d: %s' % (username,
                                                hostname,
                                                port,
                                                str(e)))
        except paramiko.BadAuthenticationType as e:
            self.transport = None
            self.info('failed: %s@%s:%d: %s' % (username,
                                                hostname,
                                                port,
                                                str(e)))
 
        return self.transport is not None
 
    def run(self, cmd, input_data=None, timeout=10):
        '''
        Run a command with optional input data.
 
        Here is an example that shows how to run commands with no input:
 
            ssh = MySSH()
            ssh.connect('host', 'user', 'password')
            status, output = ssh.run('uname -a')
            status, output = ssh.run('uptime')
 
        Here is an example that shows how to run commands that require input:
 
            ssh = MySSH()
            ssh.connect('host', 'user', 'password')
            status, output = ssh.run('sudo uname -a', '<sudo-password>')
 
        @param cmd         The command to run.
        @param input_data  The input data (default is None).
        @param timeout     The timeout in seconds (default is 10 seconds).
        @returns The status and the output (stdout and stderr combined).
        '''
        self.info('running command: (%d) %s' % (timeout, cmd))
 
        if self.transport is None:
            self.info('no connection to %s@%s:%s' % (str(self.username),
                                                     str(self.hostname),
                                                     str(self.port)))
            return -1, 'ERROR: connection not established\n'
 
        # Fix the input data.
        input_data = self._run_fix_input_data(input_data)
 
        # Initialize the session.
        self.info('initializing the session')
        self.session = self.transport.open_session()
        self.session.set_combine_stderr(True)
        self.session.get_pty()
        self.session.exec_command(cmd)
        output = self._run_poll(self.session, timeout, input_data)
        return output
        #status = self.session.recv_exit_status()
        #self.info('output size %d' % (len(output)))
        #self.info('status %d' % (status))
        #return status, output

    def get_exit_status(self):
        return self.session.recv_exit_status()

 
    def connected(self):
        '''
        Am I connected to a host?
 
        @returns True if connected or false otherwise.
        '''
        return self.transport is not None
 
    def set_verbosity(self, verbose):
        '''
        Turn verbose messages on or off.
 
        @param verbose  Enable/disable verbose messages.
        '''
        if verbose > 0:
            self.logger.setLevel(logging.INFO)
        else:
            self.logger.setLevel(logging.ERROR)
 
    def _run_fix_input_data(self, input_data):
        '''
        Fix the input data supplied by the user for a command.
 
        @param input_data  The input data (default is None).
        @returns the fixed input data.
        '''
        if input_data is not None:
            if len(input_data) > 0:
                if '\\n' in input_data:
                    # Convert \n in the input into new lines.
                    lines = input_data.split('\\n')
                    input_data = '\n'.join(lines)
            return input_data.split('\n')
        return []
 
    def _run_send_input(self, session, stdin, input_data):
        '''
        Send the input data.
 
        @param session     The session.
        @param stdin       The stdin stream for the session.
        @param input_data  The input data (default is None).
        '''
        if input_data is not None:
            self.info('session.exit_status_ready() %s' % str(session.exit_status_ready()))
            self.info('stdin.channel.closed %s' % str(stdin.channel.closed))
            if stdin.channel.closed is False:
                self.info('sending input data')
                stdin.write(input_data)
 
    def _run_poll(self, session, timeout, input_data):
        '''
        Poll until the command completes.
 
        @param session     The session.
        @param timeout     The timeout in seconds.
        @param input_data  The input data.
        @returns the output
        '''
        interval = 0.1
        maxseconds = timeout
        maxcount = maxseconds / interval
 
        # Poll until completion or timeout
        # Note that we cannot directly use the stdout file descriptor
        # because it stalls at 64K bytes (65536).
        input_idx = 0
        timeout_flag = False
        self.info('polling (%d, %d)' % (maxseconds, maxcount))
        start = datetime.datetime.now()
        start_secs = time.mktime(start.timetuple())
        output = ''
        session.setblocking(0)
        while True:
            if session.recv_ready():
                data = session.recv(self.bufsize)
                yield (data)
               
 
 
# ================================================================
# MAIN
# ================================================================
if __name__ == '__main__':
    import sys
 
    # Access variables.
    hostname = '172.23.29.118'
    port = 22
    username = 'root'
    password = 'a'
    sudo_password = 'a'  # assume that it is the same password
 
    # Create the SSH connection
    ssh = MySSH()
    ssh.set_verbosity(False)
    ssh.connect(hostname=hostname,
                username=username,
                password=password,
                port=port)
    if ssh.connected() is False:
        print( 'ERROR: connection failed.')
        sys.exit(1)
 
    def run_cmd(cmd, indata=None):
        '''
        Run a command with optional input.
 
        @param cmd    The command to execute.
        @param indata The input data.
        @returns The command exit status and output.
                 Stdout and stderr are combined.
        '''
        #print
        #print '=' * 64
        print( 'command: %s' % (cmd))
        output = ssh.run(cmd, indata, 100)
        for i in range(10):
            print (i)
            print (next(output))
        print ('status : %d' % (ssh.get_exit_status()))
        print ('output : %d bytes' % (len(output)))
        print ('%s' % (output))


    run_cmd('fio --minimal --eta=0 --status-interval=1 /root/random_read_22.fio')

