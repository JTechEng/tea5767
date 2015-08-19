#!/usr/bin/python3
# (set tabstops to 4 for everything to line up)
# Description: Test operation of a tea5767 FM tuner on i2c bus #1
# Filename: tea5767test.py
# Author: Lawrence Johnson
# History:
#	0.0		- 2015.08.14 - 	Genesis
#	0.1		- 2015.08.17 - 	added support for manual tuning, switching mono/stereo, mute, emphasis, 
#							noise cancelling, tone (trebble) reduction.
#							moved most control & status parameters inside the class structure so as 
#							to simplify writing a user-interface.
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

import smbus			# i2c bus functions
import time
import os
import configparser		# manage config file holding last known state.

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
	
	controlword = [0,0,0x10,0x10,0]		# initial values for tuning.
	statusword = [0,0,0,0,0]


	def __init__(self):
		self.i2cbus = smbus.SMBus(1)

		import fmstations		# fmstations.py has presets: ((IDENT,FREQ),(IDENT,FREQ)...)
		self.station = fmstations.station
		self.num_stations = len(self.station)

		self.config = configparser.ConfigParser()

		# build the initial state out of the last:
		try:
			self.configfile = open('tea5767.ini','r+')	
		except:
			# if it won't open, assume it's missing; create it.
			self.write_ini_file()
			self.configfile = open('tea5767.ini','r+')
		
		self.config.read('tea5767.ini')
		self.station_index = int(self.config['last state']['preset'])
		self.set_pll_values(self.station[self.station_index][1])
		if self.config['last state']['stereo'] != 'stereo-mode':
			self.toggle_stereo()
		if self.config['last state']['mute'] != 'unmuted':
			self.toggle_mute()
		if self.config['last state']['emphasis'] != 'emphasis-on':
			self.toggle_emphasis()
		if self.config['last state']['tone'] != 'tone-full':
			self.toggle_tonecontrol()
		if self.config['last state']['noise'] != 'noise-cancel-off':
			self.toggle_noisecancel()

	# Configure the init file:
	def write_ini_file(self):

		if self.controlword[2] & 0x06 != 0:
			status_mute = str('muted')
		else:
			status_mute = str('unmuted')
		if self.controlword[2] & 0x08 != 0:
			status_stereo = str('mono-mode')
		else:
			status_stereo = str('stereo-mode')
		if self.controlword[4] & 0x40 != 0:
			status_emphasis = str('emphasis-off')
		else:
			status_emphasis = str('emphasis-on')
		if self.controlword[3] & 0x02 != 0:
			status_noisecancel = str('noise-cancel-on')
		else:
			status_noisecancel = str('noise-cancel-off')
		if self.controlword[3] & 0x08 != 0:
			status_tone = str('tone-clipped')
		else:
			status_tone = str('tone-full')

		self.config['last state'] = {'preset' : str(self.station_index),\
									 'stereo' : status_stereo,\
									 'mute' : status_mute,\
									 'emphasis' : status_emphasis,\
									 'tone' : status_tone,\
									 'noise' : status_noisecancel}
		self.configfile = open('tea5767.ini','w')
		self.config.write(self.configfile)
		#close(self.configfile)
		

	# -if called with a 0, return the next station down, else next station up.
	# -pll values in the control word are set here.
	# -frequency to be tuned is returned.
	def changestation(self,direction):

		if direction == self.down and self.Ftune <= self.station[self.station_index][1]:
			if self.station_index <= 0:
				self.station_index = self.num_stations - 1
			else:
				self.station_index -= 1
		elif direction == self.up and self.Ftune >= self.station[self.station_index][1]:
			if self.station_index >= self.num_stations - 1:
				self.station_index = 0
			else:
				self.station_index += 1

		self.set_pll_values(self.station[self.station_index][1])

		return self.station[self.station_index][1]

	def update_preset_index(self):
		# keep the index close to the tuned frequency for when the user goes back to tuning presets.
		if self.Ftune < self.station[self.station_index][1]:
			if self.station_index > 0:
				if self.Ftune == self.station[self.station_index - 1][1]:
					self.station_index -= 1
		elif self.Ftune > self.station[self.station_index][1]:
			if self.station_index < self.num_stations - 2:
				if self.Ftune == self.station[self.station_index + 1][1]:
					self.station_index += 1

	# The TEA5767 is able to tune with either high- or low-side local oscillator injection;
	# the calculation of pll value is different depending on which is used:

	def set_pll_values(self,Ftune):

		# Keep the desired frequency inside the fm band.
		if Ftune < 87500000:
			Ftune = 107900000
		elif Ftune > 107900000:
			Ftune = 87500000
		
		self.Ftune = Ftune	# save this for manual tuning.
		
		pll_hsi = int(4 * (Ftune + self.Fif) / self.Fref)
		pll_lsi = int(4 * (Ftune - self.Fif) / self.Fref)
	
		self.controlword[0] = pll_hsi >> 8 & 0x3f
		self.controlword[1] = pll_hsi & 0xff

		self.update_preset_index()		# keep the presets near in value
		

	def write_control(self):
		# Note: This looks perfect on the oscilloscope; I2C is running at 100KHz.
		self.i2cbus.write_i2c_block_data(self.i2c_address,self.controlword[0],[self.controlword[1],\
						self.controlword[2],self.controlword[3],self.controlword[4]])	# configure the tuner.
		
	# read_i2c_block_data takes 3 parameters: i2C address, subcommand, # of
	# registers to read. There is no way of killing the I2C address sub-command.
	# The tea5767 is not expecting a command, so instead of issuing a 0, issue
	# the first byte of the pll reg. This seems to work rather well, as the block
	# command appears to be issuing a write before issuing the read. If it's writing,
	# the device is expecting the 6-byte sequence outlined above. Since we already
	# sent the address, it's now expecting byte #1, the pll upper bits. It then
	# terminates the write and performs the read.
	def read_status(self):
		self.statusword = self.i2cbus.read_i2c_block_data(self.i2c_address,self.controlword[0],5)	# read the tuner's status
		return self.statusword

	# a grab-bag 'o functions for toggling individual radio controls...
	def toggle_mute(self):
		if self.controlword[2] & 0x06 != 0:
			self.controlword[2] &= ~0x06
		else:
			self.controlword[2] |= 0x06
		#self.write_control()
		
	def toggle_stereo(self):
		if self.controlword[2] & 0x08 != 0:
			self.controlword[2] &= ~0x08
		else:
			self.controlword[2] |= 0x08
		#self.write_control()
		
	def toggle_emphasis(self):
		if self.controlword[4] & 0x40 != 0:
			self.controlword[4] &= ~0x40
		else:
			self.controlword[4] |= 0x40
		#self.write_control()
		
	def toggle_noisecancel(self):
		if self.controlword[3] & 0x02 != 0:
			self.controlword[3] &= ~0x02
		else:
			self.controlword[3] |= 0x02
		#self.write_control()
		
	def toggle_tonecontrol(self):
		if self.controlword[3] & 0x08 != 0:
			self.controlword[3] &= ~0x08
		else:
			self.controlword[3] |= 0x08
		#self.write_control()

	def standby(self):
		self.write_ini_file()			 # update the ini file before shutting down.
		self.controlword[3] |= 0x40		# put tuner in standby
		self.controlword[2] |= 0x06		# mute tuner
		self.write_control()			# set the tuner.

	# This is a bit misleading. Although it's showing status, status is based on
	# the values in the control register. The tuner may have rejected them.
	def show_status(self):
		if self.controlword[2] & 0x06 != 0:
			status_mute = str('muted')
		else:
			status_mute = str('unmuted')
		if self.controlword[2] & 0x08 != 0:
			status_stereo = str('mono-mode')
		else:
			status_stereo = str('stereo-mode')
		if self.controlword[4] & 0x40 != 0:
			status_emphasis = str('emphasis-off')
		else:
			status_emphasis = str('emphasis-on')
		if self.controlword[3] & 0x02 != 0:
			status_noisecancel = str('noise-cancel-on')
		else:
			status_noisecancel = str('noise-cancel-off')
		if self.controlword[3] & 0x08 != 0:
			status_tone = str('tone-clipped')
		else:
			status_tone = str('tone-full')
	
		self.read_status() 		# get the status returned by the tea5767
		
		#print(self.station_index, self.station[self.station_index][0], self.station[self.station_index][1])
		if self.Ftune == self.station[self.station_index][1]:
			print(self.station[self.station_index][1]/1000000,'MHz -',self.station[self.station_index][0],\
				status_mute,status_stereo,status_emphasis,status_noisecancel,status_tone,\
				'stat:',hex(self.statusword[0]),hex(self.statusword[1]),hex(self.statusword[2]),\
						hex(self.statusword[3]),hex(self.statusword[4]))
		else:
			print(self.Ftune/1000000,'MHz',\
				status_mute,status_stereo,status_emphasis,status_noisecancel,status_tone,\
				'stat:',hex(self.statusword[0]),hex(self.statusword[1]),hex(self.statusword[2]),\
						hex(self.statusword[3]),hex(self.statusword[4]))

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

getch = _Getch()		# insantiate the unbuffered (but still blocking) character grabber.
tuner = tea5767()		# Instantiate the tuner.

print('\nTEA5767 FM Tuner - station presets stored in fmstations.py')
print('q = quit | u = up | d = down | s = stereo/mono | m = mute')
print('n = noise-cancel | e = emphasis | t = tone full/clipped\n')

running = True
while running:

	tuner.write_control() 		# configure the tuner.
	tuner.show_status()

	# This is the whole user input system:
	user_input = getch()
	if user_input == 'u' or user_input == 'U':
		tuner.changestation(tuner.up)
	elif user_input == 'd' or user_input == 'D':
		tuner.changestation(tuner.down)
	elif user_input == '+':
		tuner.set_pll_values(tuner.Ftune + 50000)
	elif user_input == '-':
		tuner.set_pll_values(tuner.Ftune - 50000)
	elif user_input == 'm' or user_input == 'M':
		tuner.toggle_mute()
	elif user_input == 's' or user_input == 'S':
		tuner.toggle_stereo()
	elif user_input == 'e' or user_input == 'E':
		tuner.toggle_emphasis()
	elif user_input == 'n' or user_input == 'N':	
		tuner.toggle_noisecancel()
	elif user_input == 't' or user_input == 'T':
		tuner.toggle_tonecontrol()
	elif user_input == 'q':
		tuner.standby()			# turn off the radio on our way out.
		print('\nTEA5767, out!\n')
		running = False

