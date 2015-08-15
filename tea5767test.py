#!/usr/bin/python3
# Description: Test operation of a tea5767 FM tuner on i2c bus #1
# Filename: tea5767test.py
# Author: Lawrence Johnson
# History:
#	0.0		- 2015.08.14 - Genesis
#
# All comms with this device are of the format: Address, byte 1, byte 2, byte 3, byte 4, byte 5
# This is the case for both reads & writes.
# 
# All tuning is initiated by tuning the pll, and it can be set with a number corresponding to
# weather tuning is approaching the frequency from the high or low side of the actual signal.
# In this app, we are working with high-side; though the low-side calculation is included for
# brevity.
#
# Writing:
# Address is set above at 0x60.
# byte 1 = Mute, Search mode, pll[13:8]
# byte 2 = pll[7:0]
# byte 3 = search up/down, search stop level: ssl[1:0], hi/lo injection, mono/stereo, mute right, mute left, s/w port1
# byte 4 = s/w port2, standby, band-limits, clock freq, soft mute, high cut ctl, stereo noise cancel, search indicator
# byte 5 = pllref, de-emphasis ctrl, not used[5:0]
#
# for this app, Fref=32KHz, so pllref=0, clockfreq=1.
#
# Reading:
# Address is written with read-bit set
# byte 1 - rf, blf, pll[13:8]
# byte 2 - pll[7:0]
# byte 3 - stereo, if[6:0]
# byte 4 - lev[3:0] (adc output) , ci[3:1] chip-id, 0
# byte 5 - 0.

import smbus
import time
import os

class _Getch:
    def __init__(self):
        import tty, sys

    def __call__(self):
        import sys, tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch


class tea5767:

	i2c_address = 0x60			# address of device on i2c bus

	Fif = 225000				# intermodulation frequency
	Fref = 32768				# reference crystal is 32KHz.

	up,down = 1,0
	station_index = 0
	read_command = 0


	def __init__(self):
		self.i2cbus = smbus.SMBus(1)

		import fmstations		# a separate file, fmstations.py, with a tuple formatted as: ((IDENT,FREQ),(IDENT,FREQ)...)
		self.station = fmstations.station
		self.num_stations = len(self.station)

	# if called with a 0, return the next station down, else next station up.
	def changestation(self,direction):

		if direction == self.down:
			if self.station_index <= 0:
				self.station_index = self.num_stations - 1
			else:
				self.station_index -= 1
		else:
			if self.station_index >= self.num_stations - 1:
				self.station_index = 0
			else:
				self.station_index += 1
		return self.station[self.station_index][1]

	# The TEA5767 is able to tune with either high- or low-side local oscillator injection;
	# the calculation of pll value is different depending on which is used:

	def get_pll_values(self,Ftune):

		# if the requested frequency is outside the FM band, tune to the centre of the band.
		if Ftune < 87500000 | Ftune > 107900000:
			Ftune == 977000000

		pll_hsi = int(4 * (Ftune + self.Fif) / self.Fref)
		pll_lsi = int(4 * (Ftune - self.Fif) / self.Fref)
	
		pll_msb = pll_hsi >> 8 & 0x3f
		pll_lsb = pll_hsi & 0xff

		return [pll_lsb,pll_msb]

	def write_data(self,message):
		# Note: This looks perfect on the oscilloscope; I2C is running at 100KHz.
		self.i2cbus.write_i2c_block_data(self.i2c_address,message[0],[message[1],message[2],message[3],message[4]])	# configure the tuner.
		self.read_command = message[0]
		
	# read_i2c_block_data takes 3 parameters: i2C address, subcommand, # of
	# registers to read. There is no way of killing the I2C address sub-command.
	# The tea5767 is not expecting a command, so instead of issuing a 0, issue
	# the first byte of the pll reg. This seems to work rather well, as the block
	# command appears to be issuing a write before issuing the read. If it's writing,
	# the device is expecting the 6-byte sequence outlined above. Since we already
	# sent the address, it's now expecting byte #1, the pll upper bits. It then
	# terminates the write and performs the read.
	def read_data(self):
		return self.i2cbus.read_i2c_block_data(self.i2c_address,self.read_command,5)	# read the tuner's status
		

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

getch = _Getch()		# insantiate the unbuffered (but still blocking) character grabber.

tuner = tea5767()		# Instantiate the tuner.

Ftune = tuner.station[0][1]
pll = tuner.get_pll_values(Ftune)
message_out = [pll[1],pll[0],0x10,0x10,0x00]
tuner.write_data(message_out)
print('Message = ',hex(message_out[0]),' ',hex(message_out[1]),' ',hex(message_out[2]),' ',hex(message_out[3]),' ',hex(message_out[4]))
print('Tuned to',Ftune,'Hz, Station Ident:',tuner.station[0][0])

scantime = 0
station_index = 0

running = True
while running:

	message_in = tuner.read_data() # get the status.
	print('Status = ',hex(message_in[0]),' ',hex(message_in[1]),' ',hex(message_in[2]),' ',hex(message_in[3]),' ',hex(message_in[4]))
	user_input = getch()
	if user_input == 'u' or user_input == 'U':
		Ftune = tuner.changestation(tuner.up)
	elif user_input == 'd' or user_input == 'D':
		Ftune = tuner.changestation(tuner.down)
	elif user_input == 'q':
		running = False

	pll = tuner.get_pll_values(Ftune)
	message_out = [pll[1],pll[0],0x10,0x10,0x00]
	tuner.write_data(message_out) # configure the tuner.
	print('frequency = ',tuner.station[tuner.station_index][1],'Hz, Station ID:',tuner.station[tuner.station_index][0])

