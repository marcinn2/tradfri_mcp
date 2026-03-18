import os.path
import subprocess
import sys

from setuptools import setup
from setuptools.extension import Extension
from setuptools.command.build_ext import build_ext

class prepare_tinydtls(build_ext):
    def run(self):
        def run_command(args):
            print("Running:", " ".join(args))
            try:
                subprocess.check_call(args, cwd=os.path.join(os.path.dirname(__file__), "DTLSSocket","tinydtls"))
            except Exception as e:
                print(f"Trying to run {args[0]} failed, please make sure {args[0]} is installed")
                sys.exit(1)

        commands =  [
                    ["sh", "-c", "./autogen.sh"],
                    ["sh", "-c", "./configure --without-ecc"], # PSK only
                    ]
        if not os.path.exists(os.path.join(os.path.dirname(__file__), 'DTLSSocket','tinydtls','dtls.c')):
            run_command(["git", "submodule", "update", "--init"])
        for command in commands:
            run_command(command)
        build_ext.run(self)

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="DTLSSocket",
    version='0.2.3',
    license='EPL-1.0',
    description = "DTLSSocket is a cython wrapper for tinydtls with a Socket like interface",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author      = "Jannis Konrad",
    author_email= "Kabel42@gmail.com",
    url         = "https://github.com/mclab-hbrs/DTLSSocket",
    classifiers = ["License :: OSI Approved :: Eclipse Public License 1.0 (EPL-1.0)",],
    py_modules  = [ "DTLSSocket.DTLSSocket"],
    cmdclass    = {"build_ext": prepare_tinydtls},
    ext_modules = [Extension("DTLSSocket.dtls",
                [
                 "DTLSSocket/dtls.pyx",
                 "DTLSSocket/tinydtls/ccm.c",
                 "DTLSSocket/tinydtls/crypto.c",
                 "DTLSSocket/tinydtls/dtls.c",
                 "DTLSSocket/tinydtls/dtls_debug.c",
                 "DTLSSocket/tinydtls/ecc/ecc.c",
                 "DTLSSocket/tinydtls/dtls_time.c",
                 "DTLSSocket/tinydtls/hmac.c",
                 "DTLSSocket/tinydtls/netq.c",
                 "DTLSSocket/tinydtls/peer.c",
                 "DTLSSocket/tinydtls/session.c",
                 "DTLSSocket/tinydtls/aes/rijndael.c",
                 "DTLSSocket/tinydtls/aes/rijndael_wrap.c",
                 "DTLSSocket/tinydtls/sha2/sha2.c",
                 "DTLSSocket/tinydtls/platform-specific/dtls_prng_posix.c",
                 ],
                include_dirs=['DTLSSocket/tinydtls'],
                define_macros=[('DTLSv12', '1'),
                               ('WITH_SHA256', '1'),
                               ('DTLS_CHECK_CONTENTTYPE', '1'),
                               ('_GNU_SOURCE', '1'),
                                ('NDEBUG', '1'),
                                ('uint8_t', 'u_int8_t'),
                              ],
#                undef_macros = [ "NDEBUG" ],
                ),]
    )
