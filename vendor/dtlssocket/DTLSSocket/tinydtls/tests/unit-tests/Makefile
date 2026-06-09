# Makefile for tinydtls unit tests
#
# Copyright (c) 2020 Olaf Bergmann (TZI) and others.
# All rights reserved. This program and the accompanying materials
# are made available under the terms of the Eclipse Public License v1.0
# and Eclipse Distribution License v. 1.0 which accompanies this distribution.
#
# The Eclipse Public License is available at http://www.eclipse.org/legal/epl-v10.html
# and the Eclipse Distribution License is available at 
# http://www.eclipse.org/org/documents/edl-v10.php.
#

ifeq (, yes)

# the library's version
VERSION:=0.8.6

# tools

SHELL = /bin/sh
MKDIR = mkdir
CC=gcc

abs_builddir = /Users/marcin/work/tradfri_mcp/vendor/dtlssocket/DTLSSocket/tinydtls/tests/unit-tests
top_builddir = ../..
top_srcdir:= ../..

# files and flags
UNITS= test_ccm.c test_ecc.c test_prf.c
SOURCES:= $(UNITS)
PROGRAM:=testdriver
OBJECTS:= $(patsubst %.c, %.o, $(SOURCES))
HEADERS:= $(patsubst %.c, %.h, $(UNITS))
CFLAGS:=-Wall -std=c99  -g -O2 -fPIC -pedantic -Wall -Wextra -Wformat-security -Winline -Wmissing-declarations -Wmissing-prototypes -Wnested-externs -Wpointer-arith -Wshadow -Wstrict-prototypes -Wswitch-default -Wswitch-enum -Wunused  $(EXTRA_CFLAGS)
CPPFLAGS:=-I$(top_srcdir)  -DDTLSv12 -DWITH_SHA256
LDFLAGS:=-L$(top_builddir) 
LDLIBS:=$(top_srcdir)/libtinydtls.a  
DISTDIR=$(top_builddir)/tinydtls-0.8.6
FILES:=Makefile.in $(SOURCES)

.PHONY: all dirs clean distclean check

.SUFFIXES:
.SUFFIXES:      .c .o

all: $(PROGRAM)

$(PROGRAM)::	$(OBJECTS)

check:	
	./testdriver

clean:
	@rm -f $(PROGRAM) $(PROGRAM).o $(OBJECTS)
	for dir in $(SUBDIRS); do \
		$(MAKE) -C $$dir clean ; \
	done

doc:	
	$(MAKE) -C doc

distclean:	clean
	@rm -rf $(DISTDIR)
	@rm -f *~ $(DISTDIR).tar.gz

dist:	$(FILES)
	test -d $(DISTDIR)/tests/unit-tests || mkdir $(DISTDIR)/tests/unit-tests
	cp $(FILES) $(DISTDIR)/tests/unit-tests

# this directory contains no installation candidates
install:
	:

endif # HAVE_CUNIT
