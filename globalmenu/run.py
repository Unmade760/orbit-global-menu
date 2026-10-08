#!/usr/bin/python3

import os
import sys

from globalmenu.command import main as command_main

def main():
	if sys.path[0] != '':
		os.chdir(sys.path[0])

	os.environ['UBUNTU_MENUPROXY'] = '0'
	command_main()
	
if __name__ == '__main__':
	main()
