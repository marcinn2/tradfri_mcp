# the library's version
VERSION:=0.8.6
PACKAGE_TARNAME:=tinydtls

# tools

SHELL = /bin/sh
MKDIR = mkdir
DOXYGEN= :

top_builddir = ..
prefix = /usr/local
datarootdir = ${prefix}/share
docdir = ${datarootdir}/doc/${PACKAGE_TARNAME}
htmldir = ${docdir}

DISTDIR?=$(top_builddir)/tinydtls-0.8.6
FILES:=Makefile.in Doxyfile.in html

doc:	Doxyfile
	$(DOXYGEN) -l
	$(DOXYGEN) $< >./doxygen.out

clean:
	@rm -rf html

distclean:	clean
	@rm -rf $(DISTDIR)
	@rm -f *~ 

dist:	doc
	test -d $(DISTDIR)/doc || mkdir $(DISTDIR)/doc
	cp -r $(FILES) $(DISTDIR)/doc

install:	$(doc) html
	test -d $(DESTDIR)$(htmldir) || mkdir -p $(DESTDIR)$(htmldir)
	cp -r html/* $(DESTDIR)$(htmldir)

uninstall:
	for file in $(DESTDIR)$(htmldir)/* $(DESTDIR)$(htmldir)/search/*; do \
		if test -f $$file ; then $(RM) $$file ; fi ;\
	done
	if test -d $(DESTDIR)$(htmldir)/search ; then $(RMDIR) $(DESTDIR)$(htmldir)/search ; fi
	if test -d $(DESTDIR)$(htmldir) ; then $(RMDIR) $(DESTDIR)$(htmldir) ; fi
