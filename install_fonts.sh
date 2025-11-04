#!/bin/bash
apt-get update
apt-get install -y fonts-dejavu fonts-dejavu-core fonts-dejavu-extra
fc-cache -f -v
