import os
import subprocess
import re
from collections import Counter
import numpy as np
import pandas as pd

bbtools_loc = os.path.abspath("../utils/bbmap")


def run_simulation(reference_file, out_file, num_reads, len_reads=150, noisy=False):
    """
    This function runs a simulation using bbtools "randomreads.sh"
    :param reference_file: The input sequences from which to make a metagenome TODO: make this auto downsample since currently it uses the whole set
    :param out_file: the name of the output simulation (must be a FASTQ file, so ending in fq or fastq)
    :param num_reads: number of reads to simulate
    :param len_reads: how long the reads are (default is 150bp)
    :param noisy: flag if you want noise injected to the simulation
    :return:
    """
    cmd = f"{bbtools_loc}/./randomreads.sh "
    # Things we always want set to true
    simple_names = "t"
    illumina_names = "f"
    overwrite = "t"
    metagenome = "t"
    # Note: reads by default are exactly 150bp long, not paired
    cmd += f"simplenames={simple_names} overwrite={overwrite} illuminanames={illumina_names} metagenome={metagenome} "
    #cmd += f"metagenome={metagenome} "
    if noisy:
        # TODO: hard code these for now, look up realistic values later
        snprate = .01
        insrate = .01
        delrate = .01
        subrate = .01
        nrate = .01
        cmd += f"snprate={snprate} insrate={insrate} delrate={delrate} subrate={subrate} nrate={nrate} "
    cmd += f"ref={reference_file} out={out_file} reads={num_reads} length={len_reads} "
    subprocess.run(cmd, stdout=subprocess.PIPE, shell=True)
    return


def compute_rel_abundance(simulation_fq_file):
    """
    This helper function will find the true relative abundances of the sequences in the simulation
    :param simulation_fq_file: The bbmap simulated metagenome
    :return: a Counter object that contains the sequence identifiers and their counts in the simulation
    """
    # This assumes that the sequences are labeled as _._[three lower case letters}:{mixed case}_{integer}|
    regex = r'\_\.\_([a-z]{3}:[a-zA-Z]\w+)'
    contents = open(simulation_fq_file, 'r').read()
    matches = re.findall(regex, contents)
    matches_tally = Counter(matches)
    print(f"I found {len(matches_tally)} unique matches totalling {np.sum(list(matches_tally.values()))} total matches "
          f"with the most frequent one occurring {np.max(list(matches_tally.values()))} times")
    return matches_tally


def make_sketches(ksize, scale_factor, file_name, sketch_type, out_dir, per_record=False):
    """
    This helper function will create the signature/sketches using sourmash
    :param ksize: the k-size to use
    :param scale_factor: the denominator of the scale factor to use (so >=1)
    :param file_name: the file to sketch
    :param sketch_type: amino acid (aa) or nucleotide (nt)
    :param out_dir: Where to write the signature
    :param per_record: If you want sketches of each entry in the fasta file, or just of the full fasta file (default: False)
    :return: None
    """
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    out_file = f"{os.path.join(out_dir, os.path.basename(file_name))}_k_{ksize}_scale_{scale_factor}.sig"
    if sketch_type == 'aa':
        sketch_type = "protein"
    elif sketch_type == 'nt':
        sketch_type = "dna"
    else:
        raise Exception(f"Sketch_type must be one of 'aa' or 'nt. I was given {sketch_type}")
    if per_record:
        cmd = f"sourmash sketch {sketch_type} -p k={ksize},scaled={scale_factor},abund -o {out_file} --singleton {file_name}"
    else:
        cmd = f"sourmash sketch {sketch_type} -p k={ksize},scaled={scale_factor},abund -o {out_file} {file_name}"
    subprocess.run(cmd, stdout=subprocess.PIPE, shell=True)
    return


def run_sourmash_gather(query, database, out_file, sketch_type, num_results=None, threshold_bp=1000):
    """
    This is a simple wrapper for sourmash gather. It is hard coded to ignore abundances, estimate the
    ani and ci, as well as not perform the prefetch steps.
    :param query: file containing the query sketch/signature
    :param database: file containing the database sketch/signature
    :param out_file: the output csv file with the results
    :param sketch_type: aa (for amino acid) or nt (for nucleotide)
    :param num_results: int, if you only want the top N results
    :param threshold_bp: int, stop the algorithm once the overlap is below this many base pairs
    :return:
    """
    ignore_abundance = True
    estimate_ani_ci = True
    no_prefetch = True
    if sketch_type not in ['aa', 'nt']:
        raise Exception(f"sketch type must be one of aa (amino acid) or nt (nucleotide). Provided value was {sketch_type}")
    cmd = f"sourmash gather -o {out_file} "
    if ignore_abundance:
        cmd += "--ignore-abundance "
    if estimate_ani_ci:
        cmd += "--estimate-ani-ci "
    if no_prefetch:
        cmd += "--no-prefetch "
    if sketch_type == 'aa':
        cmd += "--protein "
    elif sketch_type == 'nt':
        cmd += "--dna "
    if num_results:
        cmd += f"--num-results {num_results} "
    if threshold_bp:
        cmd += f"--threshold-bp {threshold_bp} "
    cmd += f"{query} {database}"
    subprocess.run(cmd, stdout=subprocess.PIPE, shell=True)
    return


def return_unique_gather_hits(gather_out_file):
    """
    Takes a sourmash gather csv and returns the unique hits/identifiers in it
    :param gather_out_file: csv file from sourmash gather -o
    :return: a list of unique gene identifiers
    """
    if not os.path.exists(gather_out_file):
        raise Exception(f"File {gather_out_file} does not exist")
    df = pd.read_csv(gather_out_file)
    names = list(df['name'])
    name_ids = [x.split('|')[0] for x in names]
    name_ids_unique = set(name_ids)
    return list(name_ids_unique)


def cal_binary_stats(simulation_fq_file, gather_out_file):
    """
    This function takes the simulation fastq file and the gather csv out file and calculates
    binary statistics from it: a dict with keys TP, FP, FN, precision, recall, F1
    :param simulation_fq_file: Fastq file that contains the simulated reads
    :param gather_out_file: the results of running sourmash gather on those simulated reads
    :return: dict
    """
    simulation_gene_ids = set(compute_rel_abundance(simulation_fq_file).keys())
    gather_gene_ids = set(return_unique_gather_hits(gather_out_file))
    stats = dict()
    stats['TP'] = gather_gene_ids.intersection(simulation_gene_ids)
    stats['FP'] = gather_gene_ids.difference(simulation_gene_ids)
    stats['FN'] = simulation_gene_ids.difference(gather_gene_ids)
    stats['precision'] = stats['TP'] / float(stats['TP'] + stats['FP'])
    stats['recall'] = stats['TP'] / float(stats['TP'] + stats['FN'])
    stats['F1'] = 2 * stats['precision'] * stats['recall'] / float(stats['precision'] + stats['recall'])
    return stats


# TODO: make binary metric measures
# TODO: check the relative abundance calculator, since I don't think it's accurate. Note Acav_1280