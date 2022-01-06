import platform
import os
from conans import ConanFile
#from conan.tools.cmake import CMake
#from conan.tools.cmake import CMakeToolchain
#from conan.tools.layout import cmake_layout
from conans.tools import os_info, SystemPackageTool
from conan.tools.cmake import CMakeToolchain
from pathlib import PurePath, PurePosixPath


def init_impl(
    derived_conanfile,
    base_conanfile,
    repository,
    path_CPFCMake='Sources/CPFCMake',
    path_CPFBuildscripts='Sources/CPFBuildscripts',
    path_CIBuildConfigurations = 'Sources/CIBuildConfigurations'):

        base_conanfile.repository = repository
        base_conanfile.path_CPFCMake = path_CPFCMake
        base_conanfile.path_CPFBuildscripts = path_CPFBuildscripts
        base_conanfile.path_CIBuildConfigurations = path_CIBuildConfigurations

        derived_conanfile.settings = base_conanfile.settings + derived_conanfile.settings
        derived_conanfile.options = base_conanfile.options
        derived_conanfile.default_options = base_conanfile.default_options
        derived_conanfile.tool_requires = base_conanfile.tool_requires + derived_conanfile.tool_requires



class CPFBaseConanfile(object):

    # Binary configuration
    settings = "os", "arch", "compiler", "build_type"
    options = {
        "shared": [True, False],
        "CPF_CONFIG": "ANY",
        "CPF_INHERITED_CONFIG": "ANY",
        "build_target": "ANY",
        "install_target": "ANY",
        "CMAKE_GENERATOR": "ANY",
        "CMAKE_MAKE_PROGRAM": "ANY"
    }

    default_options = {
        "shared": True,
        "CPF_INHERITED_CONFIG": "PlatformIndependent",
        "build_target": "pipeline",
        "install_target": "install_all",
        "CMAKE_MAKE_PROGRAM": ""
    }

    # Dependencies
    tool_requires = "cmake/3.20.4"

    generators = "cmake"

    repository = None
    path_CPFCMake = 'Sources/CPFCMake'
    path_CPFBuildscripts = 'Sources/CPFBuildscripts'
    path_CIBuildConfigurations = 'Sources/CIBuildConfigurations'

    def package_id(self):
        # We expect no compatibility guarantees by default.
        self.info.requires.package_revision_mode()
        self.info.tool_requires.package_revision_mode()
        self.info.python_requires.package_revision_mode()

    def source(self):
        self.run("git clone --recursive {0} {1}".format(self.repository, self.source_folder))
        self.run("cd {0} && git checkout {1}".format(self.source_folder, self.version))


    def generate(self):
        """
        We use conans imports step to do the CPF configure step because the CPF configure step requires
        the directories to the dependencies that are only available after dependencies have been installed.
        This also alows developers to run the conan import step instead of the CPF 0_CopyScripts
        and 1_Configure steps. After that they can rely on the normal CPF workflow and need no
        other conan commands.
        """
        python = self.python_command()

        # The cwd is the conan install directory in this method.
        cpf_root_dir = os.getcwd().replace("\\","/") + "/../.." # This is used when running conan install.
        if self.source_folder:  # This is used when running conan create.
            cpf_root_dir = self.source_folder.replace("\\","/")

        # Sadly the package folder is not available at this point, so we use an intermediate install prefix and copy the files
        # to the package folder in an extra step.
        install_prefix = cpf_root_dir + "/install"
        test_files_dir = cpf_root_dir + "/Tests/" + str(self.options.CPF_CONFIG)

        # Generate cmake toolchain file.
        tc = CMakeToolchain(self)
        tc.generate()
        toolchain_file = self.install_folder.replace("\\","/") + "/conan_toolchain.cmake"

        # Install Buildscripts
        self.run("{0} {1}/0_CopyScripts.py --CPFCMake_DIR {2} --CIBuildConfigurations_DIR {3}".format(
            python,
            self.path_CPFBuildscripts,
            self.path_CPFCMake,
            self.path_CIBuildConfigurations
            ), cwd=cpf_root_dir)
        
        # Configure
        configure_command = "{0} 1_Configure.py {1} --inherits {2}".format(python, self.options.CPF_CONFIG, self.options.CPF_INHERITED_CONFIG) \
            + " -DCMAKE_INSTALL_PREFIX=\"{0}\"".format(install_prefix) \
            + " -DCPF_TEST_FILES_DIR=\"{0}\"".format(test_files_dir) \
            + " -DCMAKE_TOOLCHAIN_FILE=\"{0}\"".format(toolchain_file) \
            + " -DCMAKE_GENERATOR=\"{0}\"".format(self.options.CMAKE_GENERATOR) \
            + " -DCMAKE_MAKE_PROGRAM=\"{0}\"".format(self.options.CMAKE_MAKE_PROGRAM) 
            #+ " -D=\"{0}\"".format(toolchain_file) \

        self.run(configure_command, cwd=cpf_root_dir)


    def build(self):
        python = self.python_command()
        # Generate
        self.run("{0} 3_Generate.py {1} --clean".format(python, self.options.CPF_CONFIG))
        # Build
        self.run("{0} 4_Make.py {1} --target {2} --config {3}".format(
            python,
            self.options.CPF_CONFIG,
            self.options.build_target,
            self.settings.build_type
            ))
 

    def package(self):
        # Copy files into install tree.
        python = self.python_command()
        self.run("{0} 4_Make.py {1} --target {2} --config {3}".format(
            python,
            self.options.CPF_CONFIG,
            self.options.install_target,
            self.settings.build_type
            ))
        # Copy files to package directory
        self.copy("*", src="install")
 
 
    @property
    def _postfix(self):
        return self.options.debug_postfix if self.settings.build_type == "Debug" else ""
 
    def package_info(self):

        #self.cpp_info.includedirs = ['include'] # use default
        #self.cpp_info.libdirs = ['lib'] # use default
        #self.cpp_info.resdirs = ['res'] # use default
        self.cpp_info.bindirs = self.get_bin_dir()
        self.cpp_info.srcdirs = ['src']

        # TODO: Read these values from cmake package config files when
        # consumption by non-cmake projects is required.
        # self.cpp_info.libs = []  # The libs to link against
        # self.cpp_info.system_libs = []  # System libs to link against
        # self.cpp_info.build_modules = {}  # Build system utility module files (cmake files)
        # self.cpp_info.defines = []  # preprocessor definitions
        # self.cpp_info.cflags = []  # pure C flags
        # self.cpp_info.cxxflags = []  # C++ compilation flags
        # self.cpp_info.sharedlinkflags = []  # linker flags
        # self.cpp_info.exelinkflags = []  # linker flags


    def python_command(self):
        if self.settings.os == 'Windows':
            return 'python'
        else:
            return 'python3'

    def get_bin_dir(self):
        if self.settings.os_build == 'Windows':
            return ''
        else:
            return 'bin'

class CPFConanfile(ConanFile):
    name = "CPFConanfile"


