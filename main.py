#! /usr/bin/env python
import settings

import logging
log = logging.getLogger("MAIN")

try:
  import pyximport
  log.info('Gearing up with Cython')
  pyximport.install()
except Exception, e:
  log.info(e)

import settings

import urllib2
import urllib

import glob
import os
import sys

sys.path.append("lib")
import imp
import traceback
from optparse import OptionParser


import cli
IMPORT_GUI_FAILURE=False

try:
  import gui
except Exception, e:
  IMPORT_GUI_FAILURE=True
  log.info("Couldn't import GUI: %s", e)

import world

def parseOptions(opts=None):
    parser = OptionParser()
    parser.add_option("-m", "--map", dest="map",
                      help="Use map settings from MAP", default=None)
    parser.add_option("-c", "--cli", dest="cli",
                      help="Display GUI", default=False,
                      action="store_true")

    parser.add_option("-f", "--fps", dest="fps",
                      help="Frames Per Second", default=10)
    parser.add_option("-s", "--save", action="store_true",
                      help="save each world turn as a png",
                      dest="save_images", default=False)
    parser.add_option("-q", "--quiet",
                      action="store_false", dest="verbose", default=True,
                      help="don't print status messages to stdout")
    parser.add_option("--hl", "--highlight",
                      action="append", dest="highlight",
                      default=None, help="Show debugging highlights")
    parser.add_option("-i", "--ignore",
                      action="store_false", dest="whiny",
                      default=True,
                      help="ignore AI exceptions")
    parser.add_option("-n", "--ncurses",
                      action="store_true", dest="ncurses",
                      help="use curses output module, use with -c",
                      default=False)
    parser.add_option("-p", "--profile",
                      action="store_true", dest="profile",
                      help="enable profiling with cProfile",
                      default=False)
    parser.add_option("-t", "--tournament",
                      dest="tournament",
                      action="store", default=0, type=int,
                      help="Run app engine tournament")
    parser.add_option("-a", "--app-engine",
                      dest="app_engine",
                      action="store_true", default=False,
                      help="Run on google app engine")
    parser.add_option("-o", "--output",
                      dest="replay_file",
                      help="create HTML replay file")
    (options, args) = parser.parse_args(opts)
    return options,args


def loadAI(ais, highlight=False):
    if not ais:
      return

    ai_modules = []
    # for each filename, add dir to the path and then try to
    # import the actual file. if dir was not on the path
    # beforehand, make sure to pop it off again
    for filename in ais:
        try:
            log.info("Loading %s..." % (filename),)
            split_ext = os.path.splitext(filename)

            module_name = os.path.basename(split_ext[0])

            if module_name in sys.modules:
              del sys.modules[module_name]

            mod = imp.new_module(str(module_name))
            sys.modules[module_name] = mod

            mod.__file__ = filename
            execfile(filename, mod.__dict__, mod.__dict__)
            ai_modules.append(mod)
            settings.LOADED_AI_MODULES.add(mod)
            log.info("Done")

        except Exception, e:
            raise


    ai_classes = map(lambda m: getattr(m, m.AIClass),
                     ai_modules)
    return ai_classes

def loadMap(filename):

  try:
      log.info("Loading Map %s..." % (filename),)
      split_ext = os.path.splitext(filename)

      module_name = os.path.basename(split_ext[0])

      if module_name in sys.modules:
        mod = sys.modules[module_name]
      else:
        mod = imp.new_module(str(module_name))
        sys.modules[module_name] = mod

      mod.__file__ = filename
      settings.MAP_NAME=filename
      execfile(filename, mod.__dict__, mod.__dict__)

      for attr in dir(mod):
        if not attr.startswith("__"):
          log.info("Setting: %s to %s", attr, getattr(mod, attr))
          setattr(settings, attr, getattr(mod,attr))

  except Exception, e:
      log.info("Error loading %s, %s", filename, e)

def appengine_run_tournament(argv_str, tournament_key):
  from google.appengine.ext import deferred
  import tournament

  argv = argv_str.split()
  options, args = parseOptions(argv)
  ai_files = args or []
  ai_files.extend(options.highlight or [])


  for game in tournament.league_games(ai_files, options.tournament):
    deferred.defer(appengine_tournament_game, game, options.map, tournament_key)

def appengine_tournament_game(ai_files, map_file, tournament_key):
  reload(settings)
  loadMap(map_file)
  ais = loadAI(ai_files)

  settings.SINGLE_THREAD = True
  settings.IGNORE_EXCEPTIONS = True
  logging.basicConfig(level=logging.INFO)

  world = cli.appengine_main(ais, tournament_key=tournament_key)

  # Now to generate tournament compatible scores
  game_scores = {}
  for ai in world.dumpScores():
    ai_instance = world.team_map[ai["team"]]
    ai_class = ai_instance.__class__
    ai_module = ai_class.__module__
    ai_file = sys.modules[ai_module].__file__
    if ai["units"] > 0:
      game_scores[ai_file] = 1
    else:
      game_scores[ai_file] = 0

  return game_scores


def appengine_run_game(argv_str, appengine_file_name=None):
  argv = argv_str.split()
  options, args = parseOptions(argv)
  reload(settings)
  loadMap(options.map)
  ais = loadAI(args) or []
  highlighted_ais = loadAI(options.highlight, highlight=True)
  if highlighted_ais:
    ais.extend(highlighted_ais)
    settings.SHOW_HIGHLIGHTS = set(highlighted_ais)

  settings.SINGLE_THREAD = True
  settings.IGNORE_EXCEPTIONS = True
  logging.basicConfig(level=logging.INFO)

  if options.fps: settings.FPS = int(options.fps)

  cli.appengine_main(ais, appengine_file_name)

def post_to_appengine():
  import yaml
  yaml_data = open("app.yaml").read()
  app_data = yaml.load(yaml_data)
  if not settings.TOURNAMENT:
    mode = "run_game"
  else:
    mode = "run_tournament"

  if settings.APPENGINE_LOCAL:
    url_to = "http://localhost:8080/%s"%(mode)
  else:
    url_to = "http://%s.appspot.com/%s" % (app_data["application"], mode)

  data = " ".join(sys.argv[1:])
  data_str = urllib.urlencode({"argv" : data})

  print "Posting to: ", url_to
  print "Posting with:"
  print data_str
  r = urllib2.urlopen(url_to, data_str)
  print r.read()


def run_game():
  options, args = parseOptions()

  if options.tournament:
    settings.TOURNAMENT = options.tournament

  if options.app_engine:
    post_to_appengine()
    return

  logger_stream = None

  ais = loadAI(args) or []
  highlighted_ais = loadAI(options.highlight, highlight=True)
  if highlighted_ais:
    ais.extend(highlighted_ais)
    settings.SHOW_HIGHLIGHTS = set(highlighted_ais)

  loadMap(options.map)
  settings.IGNORE_EXCEPTIONS = not options.whiny
  if options.save_images:
    settings.SAVE_IMAGES = True

  if options.replay_file:
    settings.JS_REPLAY_FILENAME = options.replay_file

  if options.fps:
    settings.FPS = int(options.fps)

  if options.ncurses:
    settings.NCURSES = True
    print "Logging game to game.log"
    logger_stream = open("game.log", "w")

  logging.basicConfig(level=logging.INFO, stream=logger_stream)

  ui = cli if options.cli or IMPORT_GUI_FAILURE else gui

  try:
    ui.main(ais)
  except KeyboardInterrupt, e:
    raise
  except Exception, e:
    traceback.print_exc()
  finally:
    ui.end_threads()
    ui.end_game()


def main():
  options, args = parseOptions()
  log.info(options)
  if options.profile:
    settings.PROFILE = True
    settings.SINGLE_THREAD = True
    import cProfile

  if settings.PROFILE:
    cProfile.run("run_game()", "mainprof")
  else:
    run_game()

if __name__ == "__main__":
  main()
