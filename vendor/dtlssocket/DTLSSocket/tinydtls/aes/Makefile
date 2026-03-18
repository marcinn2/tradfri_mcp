# Makefile for tinydtls
#
# Copyright (c) 2011-2020 Olaf Bergmann (TZI) and others.
# All rights reserved. This program and the accompanying materials
# are made available under the terms of the Eclipse Public License v1.0
# and Eclipse Distribution License v. 1.0 which accompanies this distribution.
#
# The Eclipse Public License is available at http://www.eclipse.org/legal/epl-v10.html
# and the Eclipse Distribution License is available at 
# http://www.eclipse.org/org/documents/edl-v10.php.
#
# Contributors:
#    Olaf Bergmann  - initial API and implementation
#

# the library's version
VERSION:=0.8.6

# tools

SHELL = /bin/sh
MKDIR = mkdir
CC=gcc

abs_builddir = /Users/otakubar/Developer/homekit-cli/kc_tradfri_mcp/vendor/dtlssocket/DTLSSocket/tinydtls/aes
top_builddir = ..
top_srcdir:= ..

SOURCES:= rijndael.c rijndael_wrap.c
HEADERS:= rijndael.h
OBJECTS:= $(patsubst %.c, %.o, $(SOURCES))
CPPFLAGS= -DDTLSv12 -DWITH_SHA256
CFLAGS=-Wall -std=c99 -pedantic -g -O2 -fPIC -pedantic -Wall -Wextra -Wformat-security -Winline -Wmissing-declarations -Wmissing-prototypes -Wnested-externs -Wpointer-arith -Wshadow -Wstrict-prototypes -Wswitch-default -Wswitch-enum -Wunused  $(EXTRA_CFLAGS)
LDFLAGS=
LDLIBS=
FILES:=Makefile.in $(SOURCES) $(HEADERS) 
DISTDIR=$(top_builddir)/tinydtls-0.8.6

.PHONY: all dirs clean install dist distclean .gitignore doc uninstall

.SUFFIXES:
.SUFFIXES:      .c .o

all:

check:	
	echo DISTDIR: $(DISTDIR)
	echo top_builddir: $(top_builddir)

clean:
	@rm -f $(PROGRAMS) main.o $(LIB) $(OBJECTS)
	for dir in $(SUBDIRS); do \
		$(MAKE) -C $$dir clean ; \
	done

distclean:	clean
	@rm -rf $(DISTDIR)
	@rm -f *~ $(DISTDIR).tar.gz

dist:	$(FILES)
	test -d $(DISTDIR)/aes || mkdir $(DISTDIR)/aes
	cp -p $(FILES) $(DISTDIR)/aes

install:	$(HEADERS)
	test -d $(DESTDIR)$(includedir)/aes || mkdir -p $(DESTDIR)$(includedir)/aes
	$(install) $(HEADERS) $(DESTDIR)$(includedir)/aes

uninstall:
	for file in $(HEADERS); do \
		if test -f $(DESTDIR)$(includedir)/aes/$$file ; then $(RM) $(DESTDIR)$(includedir)/aes/$$file ; fi ;\
	done
	if test -d $(DESTDIR)$(includedir)/aes ; then $(RMDIR) $(DESTDIR)$(includedir)/aes ; fi

.gitignore:
	echo "core\n*~\n*.[oa]\n*.gz\n*.cap\n$(PROGRAM)\n$(DISTDIR)\n.gitignore" >$@
