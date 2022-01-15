import platform
import os
from conans import ConanFile
from conans import tools
from conans.tools import os_info, SystemPackageTool
from conan.tools.cmake import CMakeToolchain
from pathlib import PurePath, PurePosixPath

def init_impl(
    derived_conanfile,
    base_conanfile,
    repository,
    path_CPFCMake='Sources/CPFCMake',
    path_CPFBuildscripts='Sources/CPFBuildscripts',
    path_CIBuildConfigurations='Sources/CIBuildConfigurations',
    additional_cmake_options={}
    ):

        base_conanfile.repository = repository
        base_conanfile.additional_cmake_variables = additional_cmake_options
        derived_conanfile.path_CPFCMake = path_CPFCMake
        derived_conanfile.path_CPFBuildscripts = path_CPFBuildscripts
        derived_conanfile.path_CIBuildConfigurations = path_CIBuildConfigurations

        derived_conanfile.settings = base_conanfile.settings + derived_conanfile.settings
        derived_conanfile.options = base_conanfile.options
        derived_conanfile.default_options = base_conanfile.default_options
        #derived_conanfile.requires = base_conanfile.requires + derived_conanfile.requires
        derived_conanfile.build_requires = base_conanfile.build_requires + derived_conanfile.build_requires
        #derived_conanfile.tool_requires = derived_conanfile.tool_requires


def get_package_dir_cmake_options(deps_cpp_info, libs = ["ALL"]):
    """
    Returns a dictionary with "<package>_DIR" : path pairs for each dependency in the deps_cpp_info object that can be used to point
    cmake to package config files.
    """
    cmake_options = {}

    get_all =  libs[0] == "ALL"

    deps = deps_cpp_info.deps
    for dep in deps:
        use_dep = get_all or dep in libs
        if use_dep:
            lib_paths = deps_cpp_info[dep].lib_paths
            if lib_paths:
                cmake_options[dep] = (lib_paths[0] + '/cmake/MyLib').replace("\\","/")

    return cmake_options


class CPFBaseConanfile(object):

    # Binary configuration
    settings = "os", "arch", "compiler", "build_type"
    options = {
        "CPF_CONFIG" : "ANY",
        "shared": [True, False],
        "build_target": "ANY",
        "install_target": "ANY",
        "CMAKE_GENERATOR": "ANY",
        "CMAKE_MAKE_PROGRAM": "ANY",
        "CPF_ENABLE_ABI_API_COMPATIBILITY_REPORT_TARGETS": ["TRUE" , "FALSE"],
        "CPF_ENABLE_ABI_API_STABILITY_CHECK_TARGETS": ["TRUE" , "FALSE"],
        "CPF_ENABLE_ACYCLIC_TARGET": ["TRUE" , "FALSE"],
        "CPF_ENABLE_CLANG_FORMAT_TARGETS": ["TRUE" , "FALSE"],
        "CPF_ENABLE_CLANG_TIDY_TARGET": ["TRUE" , "FALSE"],
        "CPF_ENABLE_OPENCPPCOVERAGE_TARGET": ["TRUE" , "FALSE"],
        "CPF_ENABLE_PACKAGE_DOX_FILE_GENERATION": ["TRUE" , "FALSE"],
        "CPF_ENABLE_TEST_EXE_TARGETS" : ["TRUE" , "FALSE"],
        "CPF_ENABLE_RUN_TESTS_TARGET": ["TRUE" , "FALSE"],
        "CPF_ENABLE_VALGRIND_TARGET": ["TRUE" , "FALSE"],
        "CPF_WEBSERVER_BASE_DIR": "ANY",
        "CPF_TEST_FILES_DIR": "ANY",
        "CPF_VERBOSE": ["TRUE" , "FALSE"]
    }

    # The default options should do a minimalistic build that only provides the binary files to clients while building as fast as possible.
    # It does not run tests, build documentation or should do any other work.
    # If that is required, clients have to switch it on explicitly.
    default_options = {
        "CPF_CONFIG" : "Minimalistic",
        "shared": True,
        "build_target": "pipeline",
        "install_target": "install_all",
        "CMAKE_GENERATOR": "Ninja",  # Use ninja as default because be can get it on all platforms and it is performant.
        "CMAKE_MAKE_PROGRAM": "", 
        "CPF_ENABLE_ABI_API_COMPATIBILITY_REPORT_TARGETS": "FALSE",
        "CPF_ENABLE_ABI_API_STABILITY_CHECK_TARGETS": "FALSE",
        "CPF_ENABLE_ACYCLIC_TARGET": "FALSE",
        "CPF_ENABLE_CLANG_FORMAT_TARGETS": "FALSE",
        "CPF_ENABLE_CLANG_TIDY_TARGET": "FALSE",
        "CPF_ENABLE_OPENCPPCOVERAGE_TARGET": "FALSE",
        "CPF_ENABLE_PACKAGE_DOX_FILE_GENERATION": "FALSE",
        "CPF_ENABLE_TEST_EXE_TARGETS" : "FALSE",
        "CPF_ENABLE_RUN_TESTS_TARGET": "FALSE",
        "CPF_ENABLE_VALGRIND_TARGET": "FALSE",
        "CPF_WEBSERVER_BASE_DIR": "",
        "CPF_TEST_FILES_DIR": "",
        "CPF_VERBOSE": "FALSE"
    }

    # Dependencies
    build_requires = "cmake/3.21.3", "ninja/1.10.2" # Docs say we should use tool_requires, but this did not work for me. They were not downloaded.

    generators = "cmake",

    repository = None
    path_CPFCMake = None
    path_CPFBuildscripts = None
    path_CIBuildConfigurations = None

    additional_cmake_variables = {}

    def package_id(self):
            # We expect no compatibility guarantees by default.
            self.info.requires.package_revision_mode()
            self.info.python_requires.recipe_revision_mode()

    # Could not make this work
    #def build_requirements(self):
        # For now we only get the ninja build-system as build-requirement and assume that
        # make and MSBuild are preinstalled.
        #if self.options.CMAKE_GENERATOR == "Ninja":
        #    self.build_requires = ("a/b",) + ("ninja/1.10.2",)

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
        if self.options.CMAKE_GENERATOR == "Ninja":
            # Removes the CMAKE_GENERATOR_PLATFORM and CMAKE_GENERATOR_TOOLSET definitions which cause a CMake error when used with ninja.
            tc.blocks.remove("generic_system")

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
        configure_command = "{0} 1_Configure.py {1} --inherits {2}".format(python, self.options.CPF_CONFIG, "PlatformIndependent")
        # Translate package options to cmake -D options.
        self.additional_cmake_variables["CMAKE_INSTALL_PREFIX"] = install_prefix
        self.additional_cmake_variables["CMAKE_TOOLCHAIN_FILE"] = toolchain_file
        self.additional_cmake_variables["CMAKE_BUILD_TYPE"] = self.settings.build_type
        self.additional_cmake_variables["CMAKE_CONFIGURATION_TYPES"] = self.settings.build_type
        self.additional_cmake_variables["CMAKE_GENERATOR"] = self.options.CMAKE_GENERATOR
        if self.options.CMAKE_MAKE_PROGRAM != "":   # Setting an empty value here causes cmake errors.
            self.additional_cmake_variables["CMAKE_MAKE_PROGRAM"] = self.options.CMAKE_MAKE_PROGRAM
        self.additional_cmake_variables["CPF_ENABLE_ABI_API_COMPATIBILITY_REPORT_TARGETS"] = self.options.CPF_ENABLE_ABI_API_COMPATIBILITY_REPORT_TARGETS
        self.additional_cmake_variables["CPF_ENABLE_ABI_API_STABILITY_CHECK_TARGETS"] = self.options.CPF_ENABLE_ABI_API_STABILITY_CHECK_TARGETS
        self.additional_cmake_variables["CPF_ENABLE_ACYCLIC_TARGET"] = self.options.CPF_ENABLE_ACYCLIC_TARGET
        self.additional_cmake_variables["CPF_ENABLE_CLANG_FORMAT_TARGETS"] = self.options.CPF_ENABLE_CLANG_FORMAT_TARGETS
        self.additional_cmake_variables["CPF_ENABLE_CLANG_TIDY_TARGET"] = self.options.CPF_ENABLE_CLANG_TIDY_TARGET
        self.additional_cmake_variables["CPF_ENABLE_OPENCPPCOVERAGE_TARGET"] = self.options.CPF_ENABLE_OPENCPPCOVERAGE_TARGET
        self.additional_cmake_variables["CPF_ENABLE_PACKAGE_DOX_FILE_GENERATION"] = self.options.CPF_ENABLE_PACKAGE_DOX_FILE_GENERATION
        self.additional_cmake_variables["CPF_ENABLE_TEST_EXE_TARGETS"] = self.options.CPF_ENABLE_TEST_EXE_TARGETS
        self.additional_cmake_variables["CPF_ENABLE_RUN_TESTS_TARGET"] = self.options.CPF_ENABLE_RUN_TESTS_TARGET
        self.additional_cmake_variables["CPF_ENABLE_VALGRIND_TARGET"] = self.options.CPF_ENABLE_VALGRIND_TARGET
        self.additional_cmake_variables["CPF_WEBSERVER_BASE_DIR"] = self.options.CPF_WEBSERVER_BASE_DIR
        self.additional_cmake_variables["CPF_TEST_FILES_DIR"] = self.options.CPF_TEST_FILES_DIR
        self.additional_cmake_variables["CPF_VERBOSE"] = self.options.CPF_VERBOSE
        # Add client defined options
        for variable,value in self.additional_cmake_variables.items():
            configure_command = configure_command + " -D{0}=\"{1}\"".format(variable, value)
        self.run(configure_command, cwd=cpf_root_dir)


    def build(self):
        python = self.python_command()

        # For visual studio we use the vcvarsall.bat environment because I could not get ninja builds to work without it.
        environment_command = ""
        if self.settings.compiler == "Visual Studio":   # Use varsal environment when using visual studio compiler.
            environment_command = tools.vcvars_command(self) + " && "

        # Generate
        self.run(environment_command + "{0} 3_Generate.py {1} --clean".format(python, self.options.CPF_CONFIG))

        # Build
        self.run(environment_command + "{0} 4_Make.py {1} --target {2} --config {3}".format(
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
        if self.settings.os == 'Windows':
            return ''
        else:
            return 'bin'


class CPFConanfile(ConanFile):
    name = "CPFConanfile"
    description = 'Provides a basic conanfile for CPF based projects.'
    url = 'https://github.com/Knitschi/CPFConanfile'
    license = 'MIT'
    
