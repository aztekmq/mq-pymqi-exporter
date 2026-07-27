#!/bin/bash
#---------------------------------------------------------------------------
# File Name : genmqpkg.sh
# Descriptive File Name : Generate MQ runtime package
#---------------------------------------------------------------------------
#  <copyright
#  notice="lm-source-program"
#  pids="5724-H72"
#  years="2015,2025"
#  crc="0" >
#  Licensed Materials - Property of IBM
#
#  5724-H72,
#
#  (C) Copyright IBM Corp. 2015, 2025 All Rights Reserved.
#
#  US Government Users Restricted Rights - Use, duplication or
#  disclosure restricted by GSA ADP Schedule Contract with
#  IBM Corp.
#  </copyright>
#---------------------------------------------------------------------------
# @(#) MQMBID sn=p1000-L260522 su=636cd2c400c26142b34fc88b442c5ecdb2aac902 pn=install/unix/genmqpkg.sh
#---------------------------------------------------------------------------
# File Description :
# This script is used to create a smaller runtime package by creating either
# a second copy of the runtime containing only required objects or by
# removing objects that are not required from the current runtime package.
# It does this based on a number of Yes/No answers about the required
# runtime environment.
#
# Usage:
#  genmqpkg.sh [-b] [target_dir]
#  -b:         Run the program in a batch mode, making selections based
#              on environment variables. Names of the environment variables
#              are shown after running this program interactively.
#  target_dir: Where to put the new package. If creating a second copy then
#              this directory must be empty or not exist. If not provided,
#              the name is read from stdin.


# Set the incXXX variable to 1 if the environment variable
# "genmqpkg_incXXX" is also set to "1". Otherwise set it to the default
# value, usually 0.
function getenv {
  # Build the name of the environment variable dynamically
  # and use eval to get its value.
  envvarL="genmqpkg_$1"
  # Be able to handle lower and upper case variations of the env var
  envvarU=`echo $envvarL | tr '[a-z]' '[A-Z]'`
  eval val=${!envvarL}
  # If lowercase version not found, look for the uppercase version
  if [[ "$val" == "" ]]
  then
    eval val=${!envvarU}
  fi

  # Set the value in the global variable
  if [[ "$val" == "1" ]]
  then
    eval $1=1
  elif [[ "$val" == "" && "$6" == "1" ]]
  then
    eval $1=1
  else
    eval $1=0
  fi
}

function setanswer {
  eval $1=$2
  eval genmqpkg_$1=$2
}

function askinteractive {
  if [ -z "$3" -o -d "$3" ]
  then
    while true; do
        read -p "$2" yn
        case $yn in
            [Yy]* ) setanswer "$1" 1; break;;
            [Nn]* ) setanswer "$1" 0; break;;
            * ) echo "Please answer Y or N.";;
        esac
    done
  else
    eval $1=1
  fi
}

# Determine whether a component is to be included, either from the
# environment, or interactively.
function askquestion {
  if $useBatch
  then
    getenv "$@"
  else
    askinteractive "$@"
  fi
  if [ ${!1} -eq 0 ]
  then
    delfile=true
    if [ -n "$4" ]
    then
      skip_components="$skip_components $4 "
    fi
    if [ -n "$5" ]
    then
      skip_tags="$skip_tags $5 "
    fi
  fi
}

function usage {
  echo "Usage: genmqpkg.sh [-b] [target_dir]"
  echo "-b: Run non-interactively, using environment variables to configure"
  echo "target_dir: Directory to contain the regenerated package"
  echo ""
}

# Echo all parameters passed to the function when in verbose mode
function debug {
  if $verbose
  then
    echo $*
  fi
}

# Check if the specified text is found in the specified list
function match {
  text=$1
  list=$2

  [ -z "${list##* $text *}" ]
}

function tagmatch {
  IFS=':' read -ra TAGS <<< "$1"
  for file_tag in "${TAGS[@]}"
  do
    if match "$file_tag" "$2"
    then
      return 0
    fi
  done

  return 1
}

pushd `dirname $0`/.. > /dev/null
mqdir=`pwd -P`
popd > /dev/null

echo
echo "Generate MQ Runtime Package"
echo "---------------------------"
echo "This program will help determine a minimal set of runtime files that are"
echo "required for a queue manager installation or to be distributed with a"
echo "client application. The program will ask a series of questions and then"
echo "prompt for a filesystem location for the runtime files."
echo
echo "Note that IBM can only provide support assistance for an unmodified set"
echo "of runtime files."
echo

# Parse the command line arguments
useBatch=false
verbose=false
tgtdir=""
delfile=false

while [ ! -z "${1}" ]
do
  case $1 in
      "-b")
          useBatch=true            ;;
      "-h" | "-?")
          usage; exit 1            ;;
      "-v")
          verbose=true             ;;
      "-vv")
          set -x
          verbose=true             ;;
      -*)
          usage; exit 1            ;;
      *)
          break                    ;;
  esac
  command shift 2>/dev/null
done

# Target directory is final arg
if [[ $# -ge 1 ]]
then
  tgtdir=${!#}
fi

if  ! $useBatch
then
  # Clear any existing genmqpkg variables
  for var in "${!genmqpkg_@}"; do unset $var; done
fi

# Read environment variables. Default is to not include a component, that is then
# overridden by setting the envvar to "1".
askquestion inc32 "Does the runtime require 32-bit application support [Y/N]? " "" "" 32
askquestion incnls "Does the runtime require support for languages other than English [Y/N]? " "" "Msg_cs Msg_de Msg_es Msg_fr Msg_hu Msg_it Msg_ja Msg_ko Msg_pl Msg_pt Msg_Zh_CN Msg_Zh_TW" nls
askquestion inccpp "Does the runtime require C++ libraries [Y/N]? " "" "" cpp
askquestion inccbl "Does the runtime require COBOL libraries [Y/N]? " "" "" cobol
askquestion incdnet "Does the runtime require .NET libraries [Y/N]? " "" "" dotnet
delfileX=$delfile
askquestion inctls "Does the runtime require SSL/TLS support [Y/N]? "
askquestion incams "Does the runtime require AMS support [Y/N]? " "" AMS
# We can only delete GSKit if no need for SSL/TLS and no need for AMS
if [ $inctls -eq 1 ] || [ $incams -eq 1 ]
then
  incgsk=1
  delfile=$delfileX
else
  incgsk=0
  skip_components="$skip_components GSKit "
fi
askquestion inccics "Does the runtime require CICS support [Y/N]? " "" "" cics
askquestion incadm "Does the runtime require any administration tools [Y/N]? " "" "" adm
askquestion incras "Does the runtime require any RAS tools [Y/N]? " "" "" ras
askquestion incsamp "Does the runtime require any sample applications [Y/N]? " "" Samples samp
askquestion incsdk "Does the runtime require the SDK to compile applications [Y/N]? " "" SDK
askquestion incnothrd "Does the runtime require unthreaded application support [Y/N]? " "" "" unthrd
askquestion incjre "Does the runtime require a Java Runtime Environment (JRE) [Y/N]? " "$mqdir/java/jre64" JRE
askquestion incamqp "Does the runtime require AMQP support [Y/N]? " "$mqdir/amqp" AMQP
askquestion incman "Does the runtime require man pages [Y/N]? " "$mqdir/man" Man
askquestion incmqft "Does the runtime require Managed File Transfer [Y/N]? " "$mqdir/mqft" "FTAgent FTBase FTLogger FTService FTTools" mft
askquestion incmqxr "Does the runtime require Telemetry (MQXR) support [Y/N]? " "$mqdir/mqxr" XRService
askquestion incweb "Does the runtime require the MQ Console or REST API [Y/N]? " "$mqdir/web" Web web
# We can only delete the Java libraries if they're not needed by other components
if [ $incamqp -eq 0 ] && [ $incmqft -eq 0 ] && [ $incmqxr -eq 0 ] && [ $incweb -eq 0 ]
then
  askquestion incjava "Does the runtime require Java libraries [Y/N]? " "$mqdir/java/lib64" Java java
else
  setanswer incjava 1
fi
# We can only delete the Server component if it's not needed by other components
if [ $incams -eq 0 ] && [ $incamqp -eq 0 ] && [ $incmqft -eq 0 ] && [ $incmqxr -eq 0 ] && [ $incweb -eq 0 ]
then
  askquestion incserver "Does the runtime require local MQ server support [Y/N]? " "$mqdir/bin/security" Server "" 1
else
  setanswer incserver 1
fi
# Check if any MQ Advanced components are needed
if [ $incams -eq 0 ] && [ $incmqft -eq 0 ] && [ $incmqxr -eq 0 ]
then
  skip_tags="$skip_tags advanced "
fi

# See if anything can be deleted. If nothing, then there's no point
# continuing.
if ! $delfile
then
  echo
  echo "Sorry, no files can be removed from the MQ runtime package."
  exit 1
fi

# If interactive, you can keep trying to give the name of the target
# directory. If non-interactive, program exits if target already exists
# and is not empty unless it's the source directory, in which case
# unwanted files are deleted.
removeFiles=false
if [[ -z "$tgtdir" ]]
  then
  echo
  while true; do
    echo "Please provide a target directory for the MQ runtime package to be created"
    read tgtdir
    if [ "$tgtdir" = "$mqdir" ]
    then
      removeFiles=true
      break
    else
      contents=`ls -A -- "$tgtdir" 2>/dev/null`
      if [ -n "$contents" ]
      then
        echo "Target directory '$tgtdir' already exists and is not empty; please specify a new target directory or"
        echo "$mqdir to update this package."
        if $useBatch
        then
          exit
        fi
      else
        break
      fi
    fi
  done
else
  if [ "$tgtdir" = "$mqdir" ]
  then
    removeFiles=true
  else
    contents=`ls -A -- "$tgtdir" 2>/dev/null`
    if [ -n "$contents" ]
    then
      echo "Target directory '$tgtdir' already exists and is not empty; please specify a new target directory or"
      echo "$mqdir to update this package."
      exit 1
    fi
  fi
fi

echo
while true; do
    echo "The MQ runtime package will be created in"
    echo
    echo $tgtdir
    echo
    # Interactive mode gives a final chance to bail out.
    if  ! $useBatch
    then
    read -p "Are you sure you want to continue [Y/N]? " yn
    case $yn in
        [Yy]* ) break;;
        [Nn]* ) echo "Creation of MQ runtime package cancelled by user."; exit 1; break;;
        * ) echo "Please answer Y or N.";;
    esac
    else
      break
    fi
done

# Tell users how they can repeat the interactive choices in future.
if  ! $useBatch
then
  echo
  echo "To repeat this set of choices, you can set these environment"
  echo "variables and rerun this program with the -b option. The target"
  echo "directory is given as the last option on the command line."
  echo
  for var in "${!genmqpkg_@}"; do echo export $var=${!var}; done
  echo
fi

debug Components to skip: $skip_components
debug Tags to skip: $skip_tags

if [ ! -r "$mqdir/MANIFEST" ]
then
  echo "The package MANIFEST does not exist; no files can be removed from the MQ runtime package."
  exit 1
fi

# Determine on this platform how to:
# 1. copy files not following symlinks
# 2. retrieve octal permissions from stat
if [ "`uname -s`" == 'Darwin' ]
then
  cpArgs='-P -R'
  statArgs='-f %A'
else
  cpArgs='-P'
  statArgs='-c %a'
fi
debug cpArgs are $cpArgs
debug statArgs are $statArgs

# Look at all the files in the package to determine which ones we should copy
while IFS=, read -r file component checksum tags
do
  # Ignore incomplete or blank lines
  if [ -z "$tags" ]; then continue; fi

  # Ignore comments
  if [ "${file:0:1}" = '#' ]; then continue; fi

  # Ignore non-existent files
  if [ ! -e "$mqdir/$file" -a ! -L "$mqdir/$file" ]
  then
    debug Skipping file "$mqdir/$file" because it does not exist
    continue
  fi

  # Check if this file is from a component we want to skip
  if [ -n "$skip_components" ]
  then
    if match "$component" "$skip_components"
    then
      if $removeFiles
      then
        debug Removing file "$mqdir/$file" due to matching component $component
        rm -f "$mqdir/$file"
      else
        debug Skipping file "$mqdir/$file" due to matching component $component
      fi
      continue
    fi
  fi

  # Check if this file has a tag we want to skip
  if [ -n "$skip_tags" ]
  then
    if tagmatch "$tags" "$skip_tags"
    then
      if $removeFiles
      then
        debug Removing file "$mqdir/$file" due to matching tag $tags
        rm -f "$mqdir/$file"
      else
        debug Skipping file "$mqdir/$file" due to matching tag $tags
      fi
      continue
    fi
  fi

  # Delete the genmqpkg tool in the sub distribution
  if [ "$file" = "bin/genmqpkg.sh" ]
  then
    if $removeFiles
    then
      debug Removing file "$mqdir/$file"
      rm -f "$mqdir/$file"
    else
      debug Skipping file "$mqdir/$file"
    fi
    continue
  fi

  if $removeFiles
  then
    debug Leaving file "$mqdir/$file"
  else
    debug Copying file "$mqdir/$file" to "$tgtdir/$file"
    # We've determined this file should be copied
    # Create the target directory if it doesn't already exist
    if [ ! -d "$tgtdir/$(dirname $file)" ]
    then
      mkdir -p "$tgtdir/$(dirname $file)"
    fi

    # Copy the file to the target directory, not following symlinks
    cp $cpArgs "$mqdir/$file" "$tgtdir/$file"
    if [ $? -eq 0 ]
    then
      if [ ! -L "$tgtdir/$file" ]
      then
        # Retain the original permissions
        p1=`stat $statArgs "$mqdir/$file"`
        p2=`stat $statArgs "$tgtdir/$file"`
        if [ "$p1" != "$p2" ]
        then
          debug Correcting permissions of "$tgtdir/$file" from $p2 to $p1
          chmod $p1 "$tgtdir/$file"
        fi
      fi
    else
      debug "$tgtdir/$file" failed to copy
    fi
  fi
done < "$mqdir/MANIFEST"

# Tidy up any orphaned directories
if $removeFiles
then
  debug Removing any orphaned directories
  find "$mqdir" -type d -print0 | sort -zr | xargs -0 rmdir 2>/dev/null
fi

echo
echo "Generation complete !"
if $removeFiles
then
  echo "MQ runtime package created in '$mqdir'"
else
  echo "MQ runtime package copied to '$tgtdir'"
fi
echo
exit 0
