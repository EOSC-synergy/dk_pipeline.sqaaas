"""
The fundamental class for IQ Data

Xaratustrah Aug-2015

"""

import datetime
import logging as log
import os
import struct
import time
import xml.etree.ElementTree as et

import numpy as np
from scipy.io import wavfile
from scipy.signal import welch, find_peaks_cwt
from spectrum import dpss, pmtm

import pyTDMS


class IQData(object):
    """
    The main class definition
    """

    def __init__(self, filename):
        self.filename = filename
        self.file_basename = os.path.basename(filename)
        self.filename_wo_ext = os.path.splitext(filename)[0]
        self.acq_bw = 0.0
        self.center = 0.0
        self.date_time = ''
        self.number_samples = 0
        self.rbw = 0.0
        self.rf_att = 0.0
        self.fs = 0.0
        self.span = 0.0
        self.scale = 0.0
        self.header = None
        self.data_array = None
        self.lframes = 0
        self.nframes_tot = 0
        self.nframes = 0
        self.tdms_nSamplesPerRecord = 0
        self.tdms_nRecordsPerFile = 0
        self.tdms_first_rec_size = 0
        self.tdms_other_rec_size = 0
        self.tcap_scalers = None
        self.tcap_pio = None
        return

    @property
    def dictionary(self):
        return {'center': self.center, 'number_samples': self.number_samples, 'fs': self.fs,
                'nframes': self.nframes,
                'lframes': self.lframes, 'data': self.data_array,
                'nframes_tot': self.nframes_tot, 'DateTime': self.date_time, 'rf_att': self.rf_att,
                'span': self.span,
                'acq_bw': self.acq_bw,
                'file_name': self.filename, 'rbw': self.rbw}

    def __str__(self):
        return \
            '<font size="4" color="green">Record length:</font> {:.2e} <font size="4" color="green">[s]</font><br>'.format(
                self.number_samples / self.fs) + '\n' + \
            '<font size="4" color="green">No. Samples:</font> {} <br>'.format(self.number_samples) + '\n' + \
            '<font size="4" color="green">Sampling rate:</font> {} <font size="4" color="green">[sps]</font><br>'.format(
                self.fs) + '\n' + \
            '<font size="4" color="green">Center freq.:</font> {} <font size="4" color="green">[Hz]</font><br>'.format(
                self.center) + '\n' + \
            '<font size="4" color="green">Span:</font> {} <font size="4" color="green">[Hz]</font><br>'.format(
                self.span) + '\n' + \
            '<font size="4" color="green">Acq. BW.:</font> {} <br>'.format(self.acq_bw) + '\n' + \
            '<font size="4" color="green">RBW:</font> {} <br>'.format(self.rbw) + '\n' + \
            '<font size="4" color="green">RF Att.:</font> {} <br>'.format(self.rf_att) + '\n' + \
            '<font size="4" color="green">Date and Time:</font> {} <br>'.format(self.date_time) + '\n'
        # 'Scale factor: {}'.format(self.scale)

    def read_tdms_information(self, lframes=1):
        """
        Performs one read on the file in order to get the values
        :param lframes:
        :return:
        """
        # we need lframes here in order to calculate nframes_tot
        self.lframes = lframes

        # size does not matter much, because we only read 2 records, but anyway should be large enough.
        sz = os.path.getsize(self.filename)
        how_many = 0
        last_i_ff = 0
        last_q_ff = 0
        # We start with empty data
        objects = {}
        raw_data = {}

        # Read just 2 records in order to estimate the record sizes
        f = open(self.filename, "rb")
        while f.tell() < sz:
            objects, raw_data = pyTDMS.readSegment(f, sz, (objects, raw_data))

            if b"/'RecordData'/'I'" in raw_data and b"/'RecordData'/'Q'" in raw_data:
                # This record has both I and Q
                last_i = raw_data[b"/'RecordData'/'I'"][-1]
                last_q = raw_data[b"/'RecordData'/'Q'"][-1]
                offset = f.tell()

                if last_i_ff != last_i and last_q_ff != last_q:
                    how_many += 1
                    last_i_ff = last_i
                    last_q_ff = last_q
                    if how_many == 1:
                        self.tdms_first_rec_size = offset
                    if how_many == 2:
                        self.tdms_other_rec_size = offset - self.tdms_first_rec_size
                        break

        self.fs = float(objects[b'/'][3][b'IQRate'][1])
        self.rf_att = float(objects[b'/'][3][b'RFAttentuation'][1])
        self.center = float(objects[b'/'][3][b'IQCarrierFrequency'][1])
        self.date_time = time.ctime(os.path.getctime(self.filename))
        self.tdms_nSamplesPerRecord = int(objects[b'/'][3][b'NSamplesPerRecord'][1])
        self.tdms_nRecordsPerFile = int(objects[b'/'][3][b'NRecordsPerFile'][1])
        self.number_samples = self.tdms_nSamplesPerRecord * self.tdms_nRecordsPerFile
        self.nframes_tot = int(self.number_samples / lframes)

    def read_tdms(self, nframes=1, lframes=1, sframes=1):
        """
        Read from TDMS Files: Check the amount needed corresponds to how many records. Then read those records only
        and from them return only the desired amount. This way the memory footprint is smallest passible and it is
        also fast.
        :param nframes:
        :param lframes:
        :param sframes:
        :return:
        """

        self.lframes = lframes
        self.nframes = nframes

        total_n_bytes = nframes * lframes
        start_n_bytes = (sframes - 1) * lframes

        # let's see this amount corresponds to which start record
        # start at the beginning of
        start_record = int(start_n_bytes / self.tdms_nSamplesPerRecord) + 1
        starting_sample_within_start_record = start_n_bytes % self.tdms_nSamplesPerRecord

        # See how many records should we read, considering also the half-way started record?
        n_records = int((starting_sample_within_start_record + total_n_bytes) / self.tdms_nSamplesPerRecord) + 1

        # that would be too much
        if start_record + n_records > self.tdms_nRecordsPerFile:
            return

        # instead of real file size find out where to stop
        absolute_size = self.tdms_first_rec_size + (start_record + n_records - 2) * self.tdms_other_rec_size

        # We start with empty data
        objects = {}
        raw_data = {}

        f = open(self.filename, "rb")  # Open in binary mode for portability

        # While there's still something left to read
        while f.tell() < absolute_size:
            # loop until first record is filled up
            # we always need to read the first record.
            # don't jump if start record is 1, just go on reading
            if start_record > 1 and f.tell() == self.tdms_first_rec_size:
                # reached the end of first record, now do the jump
                f.seek(f.tell() + (start_record - 2) * self.tdms_other_rec_size)
            if f.tell() == self.tdms_first_rec_size:
                log.info('Reached end of first record.')
            # Now we read record by record
            objects, raw_data = pyTDMS.readSegment(f, absolute_size, (objects, raw_data))

        # ok, now close the file
        f.close()

        # up to now, we have read only the amount of needed records times number of samples per record
        # this is of course more than what we actually need.

        # convert array.array to np.array
        ii = np.frombuffer(raw_data[b"/'RecordData'/'I'"], dtype=np.int16)
        qq = np.frombuffer(raw_data[b"/'RecordData'/'Q'"], dtype=np.int16)

        # get rid of duplicates at the beginning if start record is larger than one
        if start_record > 1:
            ii = ii[self.tdms_nSamplesPerRecord:]
            qq = qq[self.tdms_nSamplesPerRecord:]

        ii = ii[starting_sample_within_start_record:starting_sample_within_start_record + total_n_bytes]
        qq = qq[starting_sample_within_start_record:starting_sample_within_start_record + total_n_bytes]

        # Vectorized is slow, so do interleaved copy instead
        self.data_array = np.zeros(2 * total_n_bytes, dtype=np.float32)
        self.data_array[::2], self.data_array[1::2] = ii, qq
        self.data_array = self.data_array.view(np.complex64)
        gain = np.frombuffer(raw_data[b"/'RecordHeader'/'gain'"], dtype=np.float64)
        self.scale = gain[0]
        self.data_array = self.data_array * self.scale
        log.info("TDMS Read finished.")

    def read_bin(self, nframes=10, lframes=1024, sframes=1):
        self.lframes = lframes
        self.nframes = nframes
        x = np.fromfile(self.filename, dtype=np.complex64)
        self.fs = float(np.real(x[0]))
        self.center = float(np.imag(x[0]))
        all_data = x[1:]
        self.number_samples = len(all_data)
        self.nframes_tot = int(self.number_samples / lframes)
        self.date_time = time.ctime(os.path.getctime(self.filename))

        total_n_bytes = nframes * lframes
        start_n_bytes = (sframes - 1) * lframes

        self.data_array = all_data[start_n_bytes:start_n_bytes + total_n_bytes]

    def read_ascii(self, nframes=10, lframes=1024, sframes=1):
        self.lframes = lframes
        self.nframes = nframes

        x = np.genfromtxt(self.filename, dtype=np.float32)
        self.fs = x[0, 0]
        self.center = x[0, 1]
        all_data = x[1:, :]
        all_data = all_data.view(np.complex64)[:, 0]
        self.number_samples = len(all_data)
        self.nframes_tot = int(self.number_samples / lframes)
        self.date_time = time.ctime(os.path.getctime(self.filename))

        total_n_bytes = nframes * lframes
        start_n_bytes = (sframes - 1) * lframes

        self.data_array = all_data[start_n_bytes:start_n_bytes + total_n_bytes]

    def read_wav(self, nframes=10, lframes=1024, sframes=1):
        """
        Read sound wave files.
        :param nframes:
        :param lframes:
        :param sframes:
        :return:
        """
        self.lframes = lframes
        self.nframes = nframes

        # activate memory map
        fs, data = wavfile.read(self.filename, mmap=True)

        all_data = data.astype(np.float32).view(np.complex64)[:, 0]
        self.fs = fs
        self.center = 0
        self.number_samples = len(all_data)
        self.nframes_tot = int(len(all_data) / lframes)
        self.date_time = time.ctime(os.path.getctime(self.filename))

        total_n_bytes = nframes * lframes
        start_n_bytes = (sframes - 1) * lframes

        self.data_array = all_data[start_n_bytes:start_n_bytes + total_n_bytes]

    def read_iq(self, nframes=10, lframes=1024, sframes=1):
        """
        Read Sony/Tektronix IQ Files
        :param nframes:
        :param lframes:
        :param sframes:
        :return:
        """
        # in iqt files, lframes is always fixed 1024 at the time of reading the file.
        # At the usage time, the lframe can be changed from time data

        self.lframes = lframes
        self.nframes = nframes

        data_offset = 0
        with open(self.filename, 'rb') as f:
            ba = f.read(1)
            data_offset += 1
            header_size_size = int(ba.decode('utf8'))
            ba = f.read(header_size_size)
            data_offset += header_size_size
            header_size = int(ba.decode('utf8'))
            ba = f.read(header_size)
            data_offset += header_size

        self.header = ba.decode('utf8').split('\n')
        header_dic = IQData.text_header_parser(self.header)

        fft_points = int(header_dic['FFTPoints'])
        max_input_level = float(header_dic['MaxInputLevel'])
        level_offset = float(header_dic['LevelOffset'])
        frame_length = float(header_dic['FrameLength'])
        gain_offset = float(header_dic['GainOffset'])
        self.center = float(header_dic['CenterFrequency'])
        self.span = float(header_dic['Span'])
        self.nframes_tot = int(header_dic['ValidFrames'])
        self.date_time = header_dic['DateTime']

        self.number_samples = self.nframes_tot * fft_points
        self.fs = fft_points / frame_length

        # self.scale = np.sqrt(np.power(10, (gain_offset + max_input_level + level_offset) / 10) / 20 * 2)
        # todo: IQ support not finished

    def read_iqt(self, nframes=10, lframes=1024, sframes=1):
        """
        Read IQT Files
        :param nframes:
        :param lframes:
        :param sframes:
        :return:
        """
        # in iqt files, lframes is always fixed 1024 at the time of reading the file.
        # At the usage time, the lframe can be changed from time data

        self.lframes = lframes
        self.nframes = nframes

        data_offset = 0
        with open(self.filename, 'rb') as f:
            ba = f.read(1)
            data_offset += 1
            header_size_size = int(ba.decode('utf8'))
            ba = f.read(header_size_size)
            data_offset += header_size_size
            header_size = int(ba.decode('utf8'))
            ba = f.read(header_size)
            data_offset += header_size

        self.header = ba.decode('utf8').split('\n')
        header_dic = IQData.text_header_parser(self.header)

        fft_points = int(header_dic['FFTPoints'])
        max_input_level = float(header_dic['MaxInputLevel'])
        level_offset = float(header_dic['LevelOffset'])
        frame_length = float(header_dic['FrameLength'])
        gain_offset = float(header_dic['GainOffset'])
        self.center = float(header_dic['CenterFrequency'])
        self.span = float(header_dic['Span'])
        self.nframes_tot = int(header_dic['ValidFrames'])
        self.date_time = header_dic['DateTime']

        self.number_samples = self.nframes_tot * fft_points
        self.fs = fft_points / frame_length

        self.scale = np.sqrt(np.power(10, (gain_offset + max_input_level + level_offset) / 10) / 20 * 2)

        log.info("Proceeding to read binary section, 32bit (4 byte) little endian.")

        frame_header_type = np.dtype(
            {'names': ['reserved1', 'validA', 'validP', 'validI', 'validQ', 'bins', 'reserved2', 'triggered',
                       'overLoad', 'lastFrame', 'ticks'],
             'formats': [np.int16, np.int16, np.int16, np.int16, np.int16, np.int16, np.int16,
                         np.int16, np.int16, np.int16, np.int32]})

        frame_data_type = np.dtype((np.int16, 2 * 1024))  # 2 byte integer for Q, 2 byte integer for I
        frame_type = np.dtype({'names': ['header', 'data'],
                               'formats': [(frame_header_type, 1), (frame_data_type, 1)]})

        total_n_bytes = nframes * frame_type.itemsize
        start_n_bytes = (sframes - 1) * frame_type.itemsize

        # prepare an empty array with enough room
        self.data_array = np.zeros(1024 * nframes, np.complex64)

        # Read n frames at once
        with open(self.filename, 'rb') as f:
            f.seek(data_offset + start_n_bytes)
            ba = f.read(total_n_bytes)

        frame_array = np.fromstring(ba, dtype=frame_type)

        for i in range(frame_array.size):
            temp_array = np.zeros(2 * 1024, np.int16)
            temp_array[::2], temp_array[1::2] = frame_array[i]['data'][1::2], frame_array[i]['data'][::2]
            temp_array = temp_array.astype(np.float32)
            temp_array = temp_array.view(np.complex64)
            self.data_array[i * 1024:(i + 1) * 1024] = temp_array
        # and finally scale the data
        self.data_array = self.data_array * self.scale
        # todo: correction data block

    def read_tiq(self, nframes=10, lframes=1024, sframes=1):
        """Process the tiq input file.
        Following information are extracted, except Data offset, all other are stored in the dic. Data needs to be normalized over 50 ohm.

        AcquisitionBandwidth
        Frequency
        File name
        Data I and Q [Unit is Volt]
        Data_offset
        DateTime
        NumberSamples
        Resolution Bandwidth
        RFAttenuation (it is already considered in the data scaling, no need to use this value, only for info)
        Sampling Frequency
        Span
        Voltage Scaling
        """

        self.lframes = lframes
        self.nframes = nframes

        filesize = os.path.getsize(self.filename)
        log.info("File size is {} bytes.".format(filesize))

        with open(self.filename) as f:
            line = f.readline()
        data_offset = int(line.split("\"")[1])

        with open(self.filename, 'rb') as f:
            ba = f.read(data_offset)

        xml_tree_root = et.fromstring(ba)

        for elem in xml_tree_root.iter(tag='{http://www.tektronix.com}AcquisitionBandwidth'):
            self.acq_bw = float(elem.text)
        for elem in xml_tree_root.iter(tag='{http://www.tektronix.com}Frequency'):
            self.center = float(elem.text)
        for elem in xml_tree_root.iter(tag='{http://www.tektronix.com}DateTime'):
            self.date_time = str(elem.text)
        for elem in xml_tree_root.iter(tag='{http://www.tektronix.com}NumberSamples'):
            self.number_samples = int(elem.text)  # this entry matches (filesize - data_offset) / 8) well
        for elem in xml_tree_root.iter('NumericParameter'):
            if 'name' in elem.attrib and elem.attrib['name'] == 'Resolution Bandwidth' and elem.attrib['pid'] == 'rbw':
                self.rbw = float(elem.find('Value').text)
        for elem in xml_tree_root.iter(tag='{http://www.tektronix.com}RFAttenuation'):
            self.rf_att = float(elem.text)
        for elem in xml_tree_root.iter(tag='{http://www.tektronix.com}SamplingFrequency'):
            self.fs = float(elem.text)
        for elem in xml_tree_root.iter('NumericParameter'):
            if 'name' in elem.attrib and elem.attrib['name'] == 'Span' and elem.attrib['pid'] == 'globalrange':
                self.span = float(elem.find('Value').text)
        for elem in xml_tree_root.iter(tag='{http://www.tektronix.com}Scaling'):
            self.scale = float(elem.text)

        log.info("Center {0} Hz, span {1} Hz, sampling frequency {2} scale factor {3}.".format(self.center, self.span,
                                                                                               self.fs, self.scale))
        log.info("Header size {} bytes.".format(data_offset))

        log.info("Proceeding to read binary section, 32bit (4 byte) little endian.")
        log.info('Total number of samples: {}'.format(self.number_samples))
        log.info("Frame length: {0} data points = {1}s".format(lframes, lframes / self.fs))
        self.nframes_tot = int(self.number_samples / lframes)
        log.info("Total number of frames: {0} = {1}s".format(self.nframes_tot, self.number_samples / self.fs))
        log.info("Start reading at offset: {0} = {1}s".format(sframes, sframes * lframes / self.fs))
        log.info("Reading {0} frames = {1}s.".format(nframes, nframes * lframes / self.fs))

        self.header = ba

        total_n_bytes = 8 * nframes * lframes  # 8 comes from 2 times 4 byte integer for I and Q
        start_n_bytes = 8 * (sframes - 1) * lframes

        with open(self.filename, 'rb') as f:
            f.seek(data_offset + start_n_bytes)
            ba = f.read(total_n_bytes)

        # return a numpy array of little endian 8 byte floats (known as doubles)
        self.data_array = np.fromstring(ba, dtype='<i4')  # little endian 4 byte ints.
        # Scale to retrieve value in Volts. Augmented assignment does not work here!
        self.data_array = self.data_array * self.scale
        self.data_array = self.data_array.view(
            dtype='c16')  # reinterpret the bytes as a 16 byte complex number, which consists of 2 doubles.

        log.info("Output complex array has a size of {}.".format(self.data_array.size))
        # in order to read you may use: data = x.item()['data'] or data = x[()]['data'] other wise you get 0-d error

    def read_tcap(self, nframes=10, lframes=1024, sframes=1):
        """
        Read TCAP fiels *.dat
        :param nframes:
        :param lframes:
        :param sframes:
        :return:
        """

        BLOCK_HEADER_SIZE = 88
        BLOCK_DATA_SIZE = 2 ** 17
        BLOCK_SIZE = BLOCK_HEADER_SIZE + BLOCK_DATA_SIZE

        self.lframes = lframes
        self.nframes = nframes
        filesize = os.path.getsize(self.filename)
        if not filesize == 15625 * BLOCK_SIZE:
            log.info("File size does not match block sizes times total number of blocks. Aborting...")
            return

        # read header section
        with open(self.filename, 'rb') as f:
            tfp = f.read(12)
            pio = f.read(12)
            scalers = f.read(64)

        # self.header = header
        #self.parse_tcap_header(header)
        self.date_time = self.parse_tcap_tfp(tfp)

        self.tcap_pio = pio
        self.tcap_scalers = scalers

        self.fs = 312500
        self.center = 1.6e5
        self.scale = 6.25e-2
        self.nframes_tot = int(15625 * 32768 / nframes)
        self.number_samples = 15625 * 32768
        self.span = 312500


        total_n_bytes = 4 * nframes * lframes  # 4 comes from 2 times 2 byte integer for I and Q
        start_n_bytes = 4 * (sframes - 1) * lframes

        ba = bytearray()
        with open(self.filename, 'rb') as f:
            f.seek(BLOCK_HEADER_SIZE + start_n_bytes)
            for i in range(total_n_bytes):
                if not f.tell() % 131160:
                    log.info('File pointer before jump: {}'.format(f.tell()))
                    log.info(
                        "Reached end of block {}. Now skipoing header of block {}!".format(int(f.tell() / BLOCK_SIZE),
                                                                                           int(
                                                                                               f.tell() / BLOCK_SIZE) + 1))
                    f.seek(88, 1)
                    log.info('File pointer after jump: {}'.format(f.tell()))
                ba.extend(f.read(1))  # using bytearray.extend is much faster than using +=

        log.info('Total bytes read: {}'.format(len(ba)))

        self.data_array = np.frombuffer(ba, '>i2')  # big endian 16 bit for I and 16 bit for Q
        self.data_array = self.data_array.astype(np.float32)
        self.data_array = self.data_array * self.scale
        self.data_array = self.data_array.view(np.complex64)

    def parse_tcap_header(self, ba):
        version = ba[0:8]
        center_freq_np = np.fromstring(ba[8:16], dtype='>f8')[0]
        center_freq = struct.unpack('>d', ba[8:16])[0]
        adc_range = struct.unpack('>d', ba[16:24])[0]
        data_scale = struct.unpack('>d', ba[24:32])[0]
        block_count = struct.unpack('>Q', ba[32:40])[0]
        block_size = struct.unpack('>I', ba[40:44])[0]
        frame_size = struct.unpack('>I', ba[44:48])[0]
        decimation = struct.unpack('>H', ba[48:50])[0]
        config_flags = struct.unpack('>H', ba[50:52])[0]
        trigger_time = ba[500:512]
        # self.fs = 10**7 / 2 ** decimation

    def parse_tcap_tfp(self, ba):
        """
        Parses the TFP Header of TCAP DAT Files. This information is coded in BCD. The
        following table was taken form the original TCAP processing files in C.
         * +------------+---------------+---------------+---------------+---------------+
         * | bit #      | 15 - 12       | 11 - 8        | 7 - 4         | 3 - 0         |
         * +------------+---------------+---------------+---------------+---------------+
         * | timereg[0] | not defined   | not defined   | status        | days hundreds |
         * | timereg[1] | days tens     | days units    | hours tens    | hours units   |
         * | timereg[2] | minutes tens  | minutes units | seconds tens  | seconds units |
         * | timereg[3] | 1E-1 seconds  | 1E-2 seconds  | 1E-3 seconds  | 1E-4 seconds  |
         * | timereg[4] | 1E-5 seconds  | 1E-6 seconds  | 1E-7 seconds  | not defined   |
         * +------------+---------------+---------------+---------------+---------------+

         here we read the first 12 bytes ( 24 nibbles ) in the tfp byte array list. First 2 bytes
         should be ignored.

        :return:
        """
        tfp = list(ba)

        dh = (tfp[3] >> 0) & 0x17

        dt = (tfp[4] >> 4) & 0x17
        du = (tfp[4] >> 0) & 0x17
        ht = (tfp[5] >> 4) & 0x17
        hu = (tfp[5] >> 0) & 0x17

        mt = (tfp[6] >> 4) & 0x17
        mu = (tfp[6] >> 0) & 0x17
        st = (tfp[7] >> 4) & 0x17
        su = (tfp[7] >> 0) & 0x17

        sem1 = (tfp[8] >> 4) & 0x17
        sem2 = (tfp[8] >> 0) & 0x17
        sem3 = (tfp[9] >> 4) & 0x17
        sem4 = (tfp[9] >> 0) & 0x17

        sem5 = (tfp[10] >> 4) & 0x17
        sem6 = (tfp[10] >> 0) & 0x17
        sem7 = (tfp[11] >> 4) & 0x17

        days = dh * 100 + dt * 10 + du
        hours = ht * 10 + hu
        minutes = mt * 10 + mu
        seconds = st * 10 + su + sem1 * 1e-1 + sem2 * 1e-2 + sem3 * 1e-3 + sem4 * 1e-4 + sem5 * 1e-5 + sem6 * 1e-6 + sem7 * 1e-7

        ts_epoch = seconds + 60 * (minutes + 60 * (hours + 24 * days))
        ts = datetime.datetime.fromtimestamp(ts_epoch).strftime('%Y-%m-%d %H:%M:%S')
        return ts

    def save_header(self):
        """Saves the header byte array into a txt tile."""
        with open(self.filename_wo_ext + '.xml', 'wb') as f3:
            f3.write(self.header)
        log.info("Header saved in an xml file.")

    def save_npy(self):
        """Saves the dictionary to a numpy file."""
        np.save(self.filename_wo_ext + '.npy', self.dictionary)

    def save_audio(self, afs):
        """ Save the singal as an audio wave """
        wavfile.write(self.filename_wo_ext + '.wav', afs, abs(self.data_array))

    def get_fft_freqs_only(self, x=None):
        if x is None:
            data = self.data_array
        else:
            data = x
        n = data.size
        ts = 1.0 / self.fs
        f = np.fft.fftfreq(n, ts)
        return np.fft.fftshift(f)

    def get_fft(self, x=None):
        """ Get the FFT spectrum of a signal over a load of 50 ohm."""
        termination = 50  # in Ohms for termination resistor
        if x is None:
            data = self.data_array
        else:
            data = x
        n = data.size
        ts = 1.0 / self.fs
        f = np.fft.fftfreq(n, ts)
        v_peak_iq = np.fft.fft(data) / n
        v_rms = abs(v_peak_iq) / np.sqrt(2)
        p_avg = v_rms ** 2 / termination
        return np.fft.fftshift(f), np.fft.fftshift(p_avg), np.fft.fftshift(v_peak_iq)

    def get_pwelch(self, x=None):
        """
        Create the power spectral density using Welch method
        :param x: if available the data segment, otherwise the whole data will be taken
        :return: fft and power in Watts
        """
        if x is None:
            data = self.data_array
        else:
            data = x
        f, p_avg = welch(data, self.fs, nperseg=data.size)
        return np.fft.fftshift(f), np.fft.fftshift(p_avg)

    def get_spectrogram(self, method='fft'):
        """
        Go through the data frame by frame and perform transformation. They can be plotted using pcolormesh
        x, y and z are ndarrays and have the same shape. In order to access the contents use these kind of
        indexing as below:

        #Slices parallel to frequency axis
        nrows = np.shape(x)[0]
        for i in range (nrows):
            plt.plot(x[i,:], z[i,:])

        #Slices parallel to time axis
        ncols = np.shape(y)[1]
        for i in range (ncols):
            plt.plot(y[:,i], z[:, i])

        :return: frequency, time and power for XYZ plot,
        """

        assert method in ['fft', 'welch', 'multitaper']

        x = self.data_array
        fs = self.fs
        nframes = self.nframes
        lframes = self.lframes

        # define an empty np-array for appending
        pout = np.zeros(nframes * lframes)

        if method == 'fft':
            # go through the data array section wise and create a results array
            for i in range(nframes):
                f, p, _ = self.get_fft(x[i * lframes:(i + 1) * lframes])
                pout[i * lframes:(i + 1) * lframes] = p

        elif method == 'welch':
            # go through the data array section wise and create a results array
            for i in range(nframes):
                f, p = self.get_pwelch(x[i * lframes:(i + 1) * lframes])
                pout[i * lframes:(i + 1) * lframes] = p

        elif method == 'multitaper':
            [tapers, eigen] = dpss(lframes, NW=2)
            f = self.get_fft_freqs_only(x[0:lframes])
            # go through the data array section wise and create a results array
            for i in range(nframes):
                p = pmtm(x[i * lframes:(i + 1) * lframes], e=tapers, v=eigen, method='adapt', show=False)
                pout[i * lframes:(i + 1) * lframes] = np.fft.fftshift(p[:, 0])

        # create a mesh grid from 0 to nframes -1 in Y direction
        xx, yy = np.meshgrid(f, np.arange(nframes))

        # fold the results array to the mesh grid
        zz = np.reshape(pout, (nframes, lframes))
        return xx, yy * lframes / fs, zz

    def get_dp_p_vs_time(self, xx, yy, zz):
        """
        Returns two arrays for plotting dp_p vs time
        :param xx: from spectrogram
        :param yy: from spectrogram
        :param zz: from spectrogram
        :return: Flattened array for 2D plot
        """
        gamma = 1.20397172736
        gamma_t = 1.34
        eta = (1 / gamma ** 2) - (1 / gamma_t ** 2)
        # Slices parallel to frequency axis
        n_time_frames = np.shape(xx)[0]
        dp_p = np.zeros(n_time_frames)
        for i in range(n_time_frames):
            fwhm, f_peak, _, _ = IQData.get_fwhm(xx[i, :], zz[i, :], skip=15)
            dp_p[i] = fwhm / (f_peak + self.center) / eta

        # Flatten array for 2D plot
        return yy[:, 0], dp_p

    def get_frame_power_vs_time(self, xx, yy, zz):
        """
        Returns two arrays for plotting frame power vs time
        :param xx: from spectrogram
        :param yy: from spectrogram
        :param zz: from spectrogram
        :return: Flattened array for 2D plot
        """
        # Slices parallel to frequency axis
        n_time_frames = np.shape(xx)[0]
        frame_power = np.zeros(n_time_frames)
        for i in range(n_time_frames):
            frame_power[i] = IQData.get_channel_power(xx[i, :], zz[i, :])

        # Flatten array for 2D plot
        return yy[:, 0], frame_power

    def get_time_average_vs_frequency(self, xx, yy, zz):
        """
        Returns the time average for each frequency bin
        :param xx:
        :param yy:
        :param zz:
        :return:
        """
        # Slices parallel to time axis (second dimension of xx is needed)
        n_frequency_frames = np.shape(xx)[1]
        f_slice_average = np.zeros(n_frequency_frames)
        for i in range(n_frequency_frames):
            f_slice_average[i] = np.average(zz[:, i])
        # Flatten array fro 2D plot (second dimension of xx is needed)
        return xx[0, :], f_slice_average

    @staticmethod
    def get_fwhm(f, p, skip=None):
        """
        Return the full width at half maximum.
        f and p are arrays of points corresponding to the original data, whereas
        the f_peak and p_peak are arrays of containing the coordinates of the peaks only
        :param f:
        :param p:
        :param skip: Sometimes peaks have a dip, skip this number of bins, use with care or visual inspection
        :return:
        """
        p_dbm = IQData.get_dbm(p)
        f_peak = p_dbm.max()
        f_p3db = 0
        f_m3db = 0
        p_p3db = 0
        p_m3db = 0
        f_peak_index = p_dbm.argmax()
        for i in range(f_peak_index, len(p_dbm)):
            if skip is not None and i < skip:
                continue
            if p_dbm[i] <= (f_peak - 3):
                p_p3db = p[i]
                f_p3db = f[i]
                break
        for i in range(f_peak_index, -1, -1):
            if skip is not None and f_peak_index - i < skip:
                continue
            if p_dbm[i] <= (f_peak - 3):
                p_m3db = p[i]
                f_m3db = f[i]
                break
        fwhm = f_p3db - f_m3db
        # return watt values not dbm
        return fwhm, f_peak, [f_m3db, f_p3db], [p_m3db, p_p3db]

    @staticmethod
    def get_narrow_peaks_dbm(f, p, accuracy=50):
        """
        Find narrow peaks and return them
        :param f:
        :param p:
        :param accuracy:
        :return:
        """
        # convert to dbm for convenience
        p_dbm = IQData.get_dbm(p)
        peak_ind = find_peaks_cwt(p_dbm, np.arange(1, accuracy))
        # return the watt value, not dbm
        return f[peak_ind], p[peak_ind]

    @staticmethod
    def get_broad_peak_dbm(f, p):
        """
        Returns the maximum usually useful for a broad peak
        :param f:
        :param p:
        :return:
        """
        # return as an array for compatibility
        return [f[p.argmax()]], [p.max()]

    @staticmethod
    def get_dbm(watt):
        """ Converter
        :param watt: value in Watt
        :return: value in dBm
        """
        return 10 * np.log10(np.array(watt) * 1000)

    @staticmethod
    def get_watt(dbm):
        """ Converter
        :param watt: value in dBm
        :return: value in Watt
        """
        return 10 ** (np.array(dbm) / 10) / 1000

    # @staticmethod
    # def get_channel_power(f, p):
    #     """ Return total power in band in Watts
    #     Input: average power in Watts
    #     """
    #     return np.trapz(p, x=f)

    def get_channel_power(self, f, p):
        """ Return total power in band in Watts
        Input: average power in Watts
        """
        summ = 0
        nbw = self.rbw * 5
        for i in range(np.size(p)):
            summ += p[i]
        # ACQ bandwidth here is a better measure.
        # correct formula uses NBW
        final = summ / np.size(p) * self.acq_bw / nbw
        return final

    @staticmethod
    def zoom_in_freq(f, p, center=0, span=1000):
        """
        Cut the frequency domain data
        :param f:
        :param p:
        :param center:
        :param span:
        :return:
        """
        low = center - span / 2
        high = center + span / 2
        mask = (f > low) & (f < high)
        return f[mask], p[mask]

    @staticmethod
    def shift_cut_data_time(x, val):
        """
        Handy tool to shift and cut data in time domain
        :param f:
        :param center:
        :return:
        """
        return x[:-val], x[val:]

    @staticmethod
    def shift_to_center_frequency(f, center):
        """
        Handy tool to shift frequency to center
        :param f:
        :param center:
        :return:
        """
        return center + f

    @staticmethod
    def text_header_parser(str):
        """
        Parses key = value from the file header
        :param str:
        :return: dictionary
        """
        dic = {}
        for line in str:
            name, var = line.partition("=")[::2]
            var = var.strip()
            var = var.replace('k', 'e3')
            var = var.replace('m', 'e-3')
            var = var.replace('u', 'e-6')
            # sometimes there is a string indicating day time:
            if 'PM' not in var and 'AM' not in var:
                var = var.replace('M', 'e6')
            dic[name.strip()] = var
        return dic
