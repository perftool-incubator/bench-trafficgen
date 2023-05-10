#!/bin/python3

import csv
import sys
import pandas as pd

collapse=1000 # ns (1 usec)
clist=[]

def max_latency(csv_file):
    with open(csv_file, "r") as csv_obj:
        csv_data = csv.reader(csv_obj)
        max_latency = max(csv_data, key=lambda val: int(val[0]))
        return round(int(max_latency[0])/collapse)

def min_latency(csv_file):
    with open(csv_file, "r") as csv_obj:
        csv_data = csv.reader(csv_obj)
        min_latency = min(csv_data, key=lambda val: int(val[0]))
        return round(int(min_latency[0])/collapse)

def sum_samples(csv_file):
    sum_samples=0
    with open(csv_file, "r") as csv_obj:
        csv_data = csv.reader(csv_obj)
        for row in csv_data:
            sum_samples += int(row[1])
        return sum_samples

def init_collapsed_list(csv_file):
    global clist
    # pre-populate collapsed latencies list w/ count=0
    clist = [[0] * 2] * (max_latency(csv_file)+1)
    for i in range(0, len(clist)):
        clist[i] = [i, 0]

def collapse_buckets(csv_file):
    global clist
    total_samples=0
    # collapse latency ranges e.g. 1001, 1500, 1999 ns --> 2 us
    with open(csv_file, "r") as csv_obj:
        csv_data = csv.reader(csv_obj)
        for row in csv_data:
            latency_usec = round(int(row[0])/collapse)
            sample_count = int(row[1])
            clist[latency_usec][1] += sample_count
            total_samples += sample_count
    return total_samples

def bucket_size_stats():
    global clist
    # smallest and largest buckets
    # list with one or more elements of the same sample count
    largest=[[0,0]] # [latency_bucket,samples]
    smallest=[[0,0]] # [latency_bucket,samples]

    for bucket in range(0, len(clist)):
        # no sample for this bucket, skip it
        if clist[bucket][1] == 0:
            continue
        # update largest (replace larger or append equal)
        if largest[0][1] == 0 or clist[bucket][1] > largest[0][1]:
            largest[0] = clist[bucket]
        elif clist[bucket][1] == largest[0][1]:
            largest.append(clist[bucket])
        # update smallest (replace smaller or append equal)
        if smallest[0][1] == 0 or clist[bucket][1] < smallest[0][1]:
            smallest[0] = clist[bucket]
        elif clist[bucket][1] == smallest[0][1]:
            smallest.append(clist[bucket])
    return largest,smallest

def bucket_minmax_samples():
    global clist
    for i in range(0, len(clist)):
        if clist[i][1] > 0:
            min_samples=i
            break
    max_samples=clist[-1][1]
    return min_samples, max_samples

def print_summary(csv_file, hist_file, total_samples):
    largest, smallest = bucket_size_stats()
    min_samples, max_samples = bucket_minmax_samples()
    summary = (
        f"\nCSV information summary:"
        f"\nInput CSV file...................................: { csv_file }."
        f"\nSum of samples count.............................: { sum_samples(csv_file) } samples."
        f"\nMax latency......................................: { max_latency(csv_file) } usec w/ { max_samples } samples."
        f"\nMin latency......................................: { min_latency(csv_file) } usec w/ { min_samples } samples."
        f"\nTotal of samples collapsed.......................: { total_samples } samples."
        f"\nCollapsing range.................................: { collapse } ns."
        f"\nLargest bucket(s) [latency,samples]..............: { largest } ({ len(largest) } buckets)."
        f"\nSmallest bucket(s) [latency,samples].............: { smallest } ({ len(smallest) } buckets)."
        f"\nCollapsed CSV file...............................: { hist_file }."
        f"\nCollapsed buckets [latency, samples].............: { clist }"
    )
    print(summary)

def write_collapsed_data_file(hist_file):
    # write to new csv file collapsed data
    with open(hist_file, "w") as csv_obj:
        hist_data = csv.writer(csv_obj)
        hist_data.writerow(["Latency", "Samples"])
        hist_data.writerows(clist)    

def merge(collapsed_files):
    f = collapsed_files.pop()
    merged_data = pd.read_csv(f)
    while len(collapsed_files) > 0:
        f = collapsed_files.pop()       
        collapsed_data = pd.read_csv(f)
        merged_data = pd.merge(merged_data, collapsed_data, on='Latency', how='outer')

    samples_columns = merged_data.filter(like='Samples_')
    merged_data['Samples'] = samples_columns.sum(axis=1)
    merged_data['Samples'] = merged_data['Samples'].astype('Int64')
    merged_data = merged_data.drop(samples_columns, axis=1)

    merged_data.to_csv('merged-buckets.csv', index=False) 
    print(f"\n'merged-buckets.csv' has been created!")


def main():

    csv_args=sys.argv

    if len(csv_args) == 0:
        exit(1)

    collapsed_files=[]

    for csv in range(1, len(csv_args)):
        csv_file = csv_args[csv]
        hist_file = f"collapsed-{csv_file}"
        init_collapsed_list(csv_file)
        total_samples = collapse_buckets(csv_file)
        write_collapsed_data_file(hist_file)
        print_summary(csv_file, hist_file, total_samples)
        collapsed_files.append(hist_file)

    if len(collapsed_files) > 1:
        merge(collapsed_files)

if __name__ == "__main__":
    exit(main())
