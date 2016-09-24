from Tribler.Core.Category.Category import Category

category = Category()

xxx_files = []
video_files = []

total = 0
total_xxx = 0
total_video = 0
false_negatives = 0
false_positives = 0

# XXX
with open('xxx_files.txt', 'r') as f:
    content = f.read()
    for line in content.split('\n'):
        xxx_files.append(line)

for name in xxx_files:
    if len(name) == 0:
        continue

    total += 1
    total_xxx += 1
    if not category.xxx_filter.isXXX(name):
        false_negatives += 1

# Video files
with open('video_files.txt', 'r') as f:
    content = f.read()
    for line in content.split('\n'):
        video_files.append(line)

for name in video_files:
    if len(name) == 0:
        continue

    total += 1
    total_video += 1
    if category.xxx_filter.isXXX(name):
        false_positives += 1

print "Total files: %d" % total
print "Total xxx files: %d" % total_xxx
print "Total video files: %d" % total_video
print "False negatives: %d (%.2f %%)" % (false_negatives, float(false_negatives) / float(total_xxx) * 100.0)
print "False positives: %d (%.2f %%)" % (false_positives, float(false_positives) / float(total_video) * 100.0)
