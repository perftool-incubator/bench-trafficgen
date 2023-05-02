#!/bin/python3

"""

v1 limitations:

    - script is not integrated to the post-processing workflow,
    and should be manually executed by users

    - collapses data from only one csv file (still can't merge
    fwd and rev files into the same output/chart)

    - units and bucket sizes are static (1 bucket = 1000 ns) 

"""


import csv
import sys

collapse=1000 # ns (1 usec)

if len(sys.argv) == 0:
    exit(1)

csv_file=sys.argv[1]
hist_file=f"collapsed-{csv_file}"

def max_latency():
    with open(csv_file, "r") as csv_obj:
        csv_data = csv.reader(csv_obj)
        max_latency = max(csv_data, key=lambda val: int(val[0]))
        return round(int(max_latency[0])/collapse)

def min_latency():
    with open(csv_file, "r") as csv_obj:
        csv_data = csv.reader(csv_obj)
        min_latency = min(csv_data, key=lambda val: int(val[0]))
        return round(int(min_latency[0])/collapse)

def sum_samples():
    sum_samples=0
    with open(csv_file, "r") as csv_obj:
        csv_data = csv.reader(csv_obj)
        for row in csv_data:
            sum_samples += int(row[1])
        return sum_samples


# pre-populate collapsed latenc[iies list w/ count=0
clist = [[0] * 2] * (max_latency()+1)
for i in range(0, len(clist)):
    clist[i] = [i, 0]

total_samples=0
# collapse latency ranges e.g. 1001, 1500, 1999 ns --> 2 us
with open(csv_file, "r") as csv_obj:
    csv_data = csv.reader(csv_obj)

    for row in csv_data:
        latency_usec = round(int(row[0])/collapse)
        sample_count = int(row[1])
        clist[latency_usec][1] += sample_count
        total_samples += sample_count

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

print("\nCollapsed list [latency bucket, samples count]:") 
print(clist)

for i in range(0, len(clist)):
    if clist[i][1] > 0:
        min_samples=i
        break
max_samples=clist[-1][1]

total=sum_samples()
summary = (
    f"\n====================================================================================================================="
    f"\nCSV information summary:"
    f"\nInput CSV file........................: { csv_file }."
    f"\nSum of samples count..................: { total } samples."
    f"\nMax latency...........................: { max_latency() } usec w/ { max_samples } samples."
    f"\nMin latency...........................: { min_latency() } usec w/ { min_samples } samples."
    f"\nTotal of samples collapsed............: { total_samples } samples."
    f"\nCollapsing range......................: { collapse } ns."
    f"\nLargest bucket(s) [latency,samples]...: { largest } ({ len(largest) } buckets)."
    f"\nSmallest bucket(s) [latency,samples]..: { smallest } ({ len(smallest) } buckets)."
    f"\nCollapsed CSV file....................: { hist_file }."
    f"\n====================================================================================================================="
)
print(summary)

# write to new csv file collapsed data
with open(hist_file, "w") as csv_obj:
    hist_data = csv.writer(csv_obj)
    hist_data.writerows(clist)    
