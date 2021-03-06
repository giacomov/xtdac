#!/usr/bin/env python

"""
Filter the event file and the exposure map, divide by CCD, then run xtdac on each CCD
"""

import argparse
import glob
import os
import sys
import shutil

import astropy.io.fits as pyfits

from XtDac.ChandraUtils import find_files
from XtDac.ChandraUtils import logging_system
from XtDac.ChandraUtils.data_package import DataPackage
from XtDac.ChandraUtils.run_command import CommandRunner
from XtDac.ChandraUtils.configuration import get_configuration
from XtDac.ChandraUtils.work_within_directory import work_within_directory
from XtDac.ChandraUtils.sanitize_filename import sanitize_filename

# This is just to make sure that CIAO is loaded
import psf
import caldb4

def filter_exposure_map(exposure_map, regions_file, eventfile, new_exposure_map, resample_factor=1):
    if regions_file.find(".reg") < 0:

        # Generate an almost empty event file which will be used by xtcheesemask to extract the WCS and the
        # characteristics of the hardware unit (i.e., of the ccd)

        with pyfits.open(eventfile) as f:

            small_data = f['EVENTS'].data[:2]
            header = f['EVENTS'].header

        new_hdu = pyfits.BinTableHDU(data=small_data, header=header)

        # Now append the region table

        with pyfits.open(regions_file) as f:

            region_hdu = f['SRCREG']

            hdu_list = pyfits.HDUList([pyfits.PrimaryHDU(), new_hdu, region_hdu])

            temp_file = '___2_events.fits'

            hdu_list.writeto(temp_file, clobber=True)

    else:

        temp_file = regions_file

    cmd_line = "xtcheesemask.py -i %s -r %s -o %s -s %s --no-reverse" \
               % (exposure_map, temp_file, new_exposure_map, resample_factor)

    runner.run(cmd_line)

    os.remove(temp_file)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Run Bayesian Block algorithm')

    parser.add_argument("-c", "--config_file", help="Path to the configuration file", type=str, required=True)

    parser.add_argument("-o", "--obsid", help="Observation ID Numbers", type=str, required=True, nargs="+")

    parser.add_argument('--simulate', help='If set, a background-only dataset is simulated from the observation and '
                                           'the algorithm is run on the simulated dataset', action='store_true')
    parser.add_argument('--simulated_data', help='set this if you are using simulated data from a previous call of '
                                                 'xtdac_acis with --simulate',
                        action='store_true')

    # parser.add_argument('-r', '--region_repo', help="Path to the repository of region files",
    #                     type=str, required=True)

    # parser.add_argument('-a', "--adj_factor",
    #                     help="If region files need to be adjusted, what factor to increase axes of ellipses by",
    #                     type=float, required=True)

    # parser.add_argument("-e1", "--emin", help="Minimum energy (eV)", type=int, required=True)
    #
    # parser.add_argument("-e2", "--emax", help="Maximum energy (eV)", type=int, required=True)
    #
    # parser.add_argument("-c", "--ncpus", help="Number of CPUs to use (default=1)",
    #                     type=int, default=1, required=False)
    #
    # parser.add_argument("-p", "--typeIerror",
    #                     help="Type I error probability for the Bayesian Blocks algorithm.",
    #                     type=float,
    #                     default=1e-5,
    #                     required=False)
    #
    # parser.add_argument("-s", "--sigmaThreshold",
    #                     help="Threshold for the final significance. All intervals found "
    #                          "by the bayesian blocks "
    #                          "algorithm which does not surpass this threshold will not be saved in the "
    #                          "final file.",
    #                     type=float,
    #                     default=5.0,
    #                     required=False)
    #
    # parser.add_argument("-m", "--multiplicity", help="Control the overlap of the regions."
    #                                                  " A multiplicity of 2 means the centers of the regions are"
    #                                                  " shifted by 1/2 of the region size (they overlap by 50 percent),"
    #                                                  " a multiplicity of 4 means they are shifted by 1/4 of "
    #                                                  " their size (they overlap by 75 percent), and so on.",
    #                     required=False, default=2.0, type=float)
    #
    # parser.add_argument("-v", "--verbosity", help="Info or debug", type=str, required=False, default='info',
    #                     choices=['info', 'debug'])

    # Get the logger
    logger = logging_system.get_logger(os.path.basename(sys.argv[0]))

    # Get the command runner
    runner = CommandRunner(logger)

    args = parser.parse_args()

    # Get the configuration
    config = get_configuration(args.config_file)

    # Get work directory and sanitize it
    work_directory = sanitize_filename(config['work directory'])

    # Now remove [ and ] (which might be there if the user is running jobs array on PBS). They would confuse
    # CIAO executables
    work_directory = work_directory.replace("[","").replace("]","")

    # Check whether we need to remove the workdir or not

    remove_work_dir = bool(config['remove work directory'])

    # Now move in the work directory and do the processing
    # Encapsulate all in a try/except clause so that even in case of errors we have the opportunity to clean up
    # the workdir
    try:

        for this_obsid in args.obsid:

            with work_within_directory(os.path.join(work_directory, "__%s" % str(this_obsid)), create=True,
                                       remove=remove_work_dir):

                # Get the data package for the input data
                data_package = DataPackage(os.path.join(config['data repository'], str(this_obsid)))

                # If we are in simulation mode, simulate a new dataset and create a new data package to be used
                # instead
                if args.simulate:

                    logger.info("Simulating data...")

                    # NOTE: .get() will copy the files here
                    bkgmap = data_package.get("bkgmap")
                    asolfile = data_package.get("asol")
                    evtfile = data_package.get('evt3')
                    expfile = data_package.get('exp3')

                    sim_evt_file = "%s_sim.fits" % (os.path.splitext(os.path.basename(evtfile.filename))[0])

                    cmd_line = "xtc_simulate_bkg.py --bkgmap %s --expomap %s --evtfile %s --asolfile %s " \
                               "--outfile %s" % (bkgmap.filename, expfile.filename, evtfile.filename,
                                                 asolfile.filename, sim_evt_file)

                    runner.run(cmd_line)

                    logger.info("Creating new data package")

                    sim_dir = '_simulations'

                    if os.path.exists(sim_dir):

                        shutil.rmtree(sim_dir)

                    os.makedirs(sim_dir)

                    # Override the input data package with a new one

                    data_package = data_package.copy_to(sim_dir)

                    # Make temporarily read-write so we can update the event file

                    data_package.read_only = False

                    # Override in the new one the event file (so all subsequent commands will use that one)
                    data_package.store("evt3", sim_evt_file, "Simulated event file", force=True)

                    # Overrite in the new one the exposure map that has been modified (so all subsequent commands will
                    # use that one)
                    data_package.store("exp3", expfile.filename, "Simulated exposure map", force=True)

                    # Restore read-only status

                    data_package.read_only = True

                    # Make a specific output package (so we don't risk to overwrite an existing output package for real
                    # data)
                    out_package = DataPackage("%s_sim" % str(this_obsid), create=True)

                else:

                    out_package = DataPackage(str(this_obsid), create=True)

                # Make sure the output package is empty, otherwise emtpy it
                out_package.clear()

                # Start the processing

                # NOTE: .get() will copy the file here

                evtfile = data_package.get('evt3')
                tsvfile = data_package.get('tsv')
                expfile = data_package.get('exp3')

                #######################################
                # Filtering
                #######################################

                # Figure out the path for the regions files for this obsid

                region_dir = os.path.join(os.path.expandvars(os.path.expanduser(config['region repository'])),
                                          '%s' % int(this_obsid.split("_")[0]))

                # If we are simulating, there is no need to randomize the time (the simulation does not discretize
                # the arrival times into frames). Otherwise, if we are dealing with true data, we need to randomize
                # the arrival time within each frame time

                if args.simulate or args.simulated_data:

                    additional_options = '--simulation_mode'

                else:

                    additional_options = ''

                cmd_line = "xtc_filter_event_file.py --region_dir %s --in_package %s --out_package %s " \
                           "--emin %d --emax %d " \
                           "--adj_factor %s %s" \
                           % (region_dir, data_package.location, out_package.location,
                              config['energy min'], config['energy max'], config['adjustment factor'],
                              additional_options)

                runner.run(cmd_line)

                # Products are: filtered_evt3, all_regions and (if any) streak_regions_ds9

                ###### Remove hot pixels

                events_no_hot_pixels = '%s_filtered_nohot.fits' % this_obsid

                cmd_line = "xtc_prefilter_hot_pixels.py --evtfile %s --outfile %s" \
                           % (out_package.get('filtered_evt3').filename, events_no_hot_pixels)

                runner.run(cmd_line)

                out_package.store('filtered_nohot', events_no_hot_pixels,
                                  "Filtered event file (evt3) with events in hot pixels removed")

                #######################################
                # Separate CCDs
                #######################################

                cmd_line = "xtc_separate_CCDs.py --evtfile %s" % out_package.get('filtered_nohot').filename

                runner.run(cmd_line)

                pattern = 'ccd_*_%s' % os.path.basename(out_package.get('filtered_nohot').filename)

                ccd_files = find_files.find_files('.', pattern)

                assert len(ccd_files) > 0, "No CCD in this observation?? This is likely a bug. " \
                                           "I was looking for %s" % (pattern)

                #######################################
                # Run Bayesian Block on each CCD
                #######################################

                for ccd_file in ccd_files:

                    # Get the root of the ccd filename and the ccd number (will be used to name the files)

                    ccd_root = os.path.splitext(os.path.basename(ccd_file))[0]

                    ccd_number = os.path.basename(ccd_file).split("_")[1]

                    logger.info("########################################")
                    logger.info("Processing CCD %s..." % ccd_number)
                    logger.info("########################################")

                    # First filter the exposure map

                    filtered_expomap = 'ccd_%s_filtered_expomap.fits' % ccd_number

                    # xtcheesemask, used by filter_exposure_map, cannot overwrite files, so delete the file
                    # if existing

                    try:

                        os.remove(filtered_expomap)

                    except:

                        pass

                    # NOTE: use only a resample factor of 1, or the destreaking will fail

                    filter_exposure_map(data_package.get('exp3').filename, out_package.get('all_regions').filename,
                                        ccd_file, filtered_expomap, resample_factor=1)

                    if out_package.has('streak_regions_ds9'):
                        # Filter also for the streaks

                        temp_file = '__expomap_temp.fits'

                        filter_exposure_map(filtered_expomap, out_package.get('streak_regions_ds9').filename,
                                            ccd_file, temp_file, resample_factor=1)

                        os.remove(filtered_expomap)
                        os.rename(temp_file, filtered_expomap)

                    # Register the filtered expomap

                    out_package.store('ccd_%s_filtered_expomap' % ccd_number, filtered_expomap,
                                      "Expomap for CCD %s, filtered for all the regions which have been "
                                      "used for the event file" % ccd_number)

                    ###### XTDAC #########

                    cmd_line = "xtdac.py -e %s -x %s -w yes -c %s -p %s -s %s -m %s -v %s --max_duration 50000 " \
                               "--transient_pos --min_number_of_events %i" \
                               % (ccd_file, filtered_expomap, config['number of processes'],
                                  config['type I error probability'],
                                  config['sigma threshold'], config['multiplicity'], config['verbosity'],
                                  config['min number of events'])

                    runner.run(cmd_line)

                    #####################

                    # Now register the output in the output data package
                    baseroot = os.path.splitext(ccd_file)[0]

                    out_package.store("ccd_%s_raw_list" % ccd_number, "%s_res.txt" % baseroot,
                                      "Unfiltered list of candidates for CCD %s (output of xtdac)" % ccd_number)

                    out_package.store("ccd_%s_xtdac_html" % ccd_number,
                                      "%s_res.html" % baseroot,
                                      "HTML file produced by xtdac, containing the unfiltered list of candidates "
                                      "for ccd %s" % ccd_number)

                    output_files = glob.glob("%s_*candidate*.reg" % baseroot)

                    for i, output in enumerate(output_files):
                        reg_id = output.split("_")[-1].split(".reg")[0]

                        out_package.store("%s_candidate_reg%s" % (baseroot, reg_id), output,
                                          "Ds9 region file for candidate %s" % reg_id)

                    #######################################
                    # Filter candidate list
                    #######################################

                    # Hot pixels

                    check_hp_file = "check_hp_%s_%s.txt" % (ccd_number, this_obsid)

                    cmd_line = "xtc_remove_hot_pixels.py --obsid %s --evtfile %s --bbfile %s --outfile %s --debug no" \
                               % (this_obsid, ccd_file, "%s_res.txt" % baseroot, check_hp_file)

                    runner.run(cmd_line)

                    # Register output

                    out_package.store("ccd_%s_check_hp" % ccd_number, check_hp_file,
                                      "List of candidates for CCD %s with hot pixels flagged" % ccd_number)

                    # Variable sources

                    check_var_file = "check_var_%s_%s.txt" % (ccd_number, this_obsid)

                    cmd_line = "xtc_flag_near_variable_sources.py --bbfile %s --outfile %s --eventfile %s" \
                               % (check_hp_file, check_var_file, ccd_file)

                    runner.run(cmd_line)

                    # Register output

                    out_package.store("ccd_%s_check_var" % ccd_number, check_var_file,
                                      "List of candidates for CCD %s with hot pixels and "
                                      "variable sources flagged" % ccd_number)

                # Now add candidates to master list (one list for this obsid)

                candidate_file = "%s_all_candidates.txt" % this_obsid

                cmd_line = "xtc_add_to_masterlist.py --package %s --masterfile %s" % (out_package.location,
                                                                                      candidate_file)

                runner.run(cmd_line)

                # Reopen the file and write the command line which generated this analysis as a comment
                with open(candidate_file, "a") as f:

                    f.write("\n# command line:\n# %s\n" % " ".join(sys.argv))

                out_package.store("candidates", candidate_file, "List of all candidates found in all CCDs")

                # Now make the GIFs with the candidate transients
                cmd_line = "xtc_gif_generator.py --masterfile %s" % candidate_file

                runner.run(cmd_line)

                # Register files
                animated_gifs = glob.glob("*_cand_*.gif")

                for animated_gif in animated_gifs:

                    root = os.path.splitext(animated_gif)[0]

                    out_package.store(root, animated_gif, "Animation of the transient %s" % root)

                # Move package to output repository

                logger.info("Move the results to the output repository %s" % config['output repository'])

                out_repo_dir = sanitize_filename(config['output repository'])

                if not os.path.exists(out_repo_dir):

                    logger.info("Creating directory %s" % out_repo_dir)

                    os.makedirs(out_repo_dir)

                out_package.copy_to(out_repo_dir)
    except:

        raise

    finally:


        if remove_work_dir and config['work directory'] != '.':

            shutil.rmtree(work_directory)
