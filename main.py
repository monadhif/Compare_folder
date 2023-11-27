import difflib
import json
import logging
from filecmp import dircmp
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

def configure_logging(log_file_path):
    """Configure the logging module."""
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s',filename=log_file_path, level=logging.INFO)

#Enhance the report method of the dircmp class to facilitate writing the investigation report directly to the log file

def report_full_closure_to_log(self, logger):
    """Report on self and subdirs recursively to the specified logger."""
    self.report_to_log(logger)
    for sd in self.subdirs.values():
        logger.info("")
        sd.report_full_closure_to_log(logger)

def report_to_log(self, logger):
    """Print a clean report message to the specified logger."""
    logger.info(f"Diff {self.left} and {self.right}")
    if self.left_only:
        self.left_only.sort()
        logger.info(f'Only in {self.left}: {self.left_only}')
    if self.right_only:
        self.right_only.sort()
        logger.error(f'Only in {self.right}: {self.right_only}')
    if self.same_files:
        self.same_files.sort()
        logger.info(f'Identical files: {self.same_files}')
    if self.diff_files:
        self.diff_files.sort()
        logger.warning(f'Differing files: {self.diff_files}')
    if self.funny_files:
        self.funny_files.sort()
        logger.error(f'Trouble with common files: {self.funny_files}')
    if self.common_dirs:
        self.common_dirs.sort()
        logger.info(f'Common subdirectories: {self.common_dirs}')
    if self.common_funny:
        self.common_funny.sort()
        logger.error(f'Common funny cases: {self.common_funny}')

# Add the modified methods to the dircmp class
dircmp.report_full_closure_to_log = report_full_closure_to_log
dircmp.report_to_log = report_to_log

def is_float(value):
    """check if the string is a float
    """
    try:
        float(value)
        return True
    except ValueError:
        return False

def compare_floats(value1, value2, precision=2):
    """Compares two float values with a specified precision.
    """
    return round(float(value1), precision) == round(float(value2), precision)

def get_different_parts(list_diff, thresh=2):
    """Extracts different parts from a the lines with a given threshold for float part.
    """
    differ_parts = {"ignored_path_diff": [], "ignored_float_diff": [], "critical_diff": []}

    break_outer = False  # Flag to break out of the outer loop

    for i in range(0, len(list_diff), 2):
        differ_item_1 = list_diff[i].replace("\n", "").split(";")
        differ_item_2 = list_diff[i + 1].replace("\n", "").split(";")

        for item_1, item_2 in zip(differ_item_1, differ_item_2):
            if item_1 != item_2:
                if is_float(item_1) and compare_floats(item_1, item_2, precision=thresh):
                    differ_parts["ignored_float_diff"].append(item_2)
                elif Path(item_1.strip()).is_absolute():
                    differ_parts["ignored_path_diff"].append(item_2)
                else:
                    differ_parts["critical_diff"].append(item_2)
                    break_outer = True  # Set the flag to break the outer loop
                    break  # Break out of the inner loop
            
        if break_outer:
            break  # Break out of the outer loop

    return differ_parts

def compare_files(file1_path, file2_path, thresh=2):
    """Compares two text files and identifies differences.
    """
    with open(file1_path, 'r') as file1, open(file2_path, 'r') as file2:
        lines1 = file1.readlines()
        lines2 = file2.readlines()

    differ = difflib.Differ()
    diff = list(differ.compare(lines1, lines2))
    different_lines = [line[2:] for line in diff if line.startswith('- ') or line.startswith('+ ')]
    if file1_path.suffix.lower() == '.csv':
        different_lines = different_lines[1:]
    if len(different_lines) % 2 == 0:
        return get_different_parts(different_lines, thresh) 
    else:
        return {"ignored_path_diff": [], "ignored_float_diff": [], "critical_diff": ["all"]}

def check_absent_elements(dcmp, diff_dict):
    """Check for elements only in the original folder."""
    if dcmp.left_only:
        logging.info("Elements exist only in the original folder but not in the modified folder.")
        files_names = [item for item in dcmp.left_only if "." in item]
        diff_dict["folder"].extend(set(dcmp.left_only).difference(set(files_names)))
        diff_dict["folder"] = [str(Path(dcmp.left, item)) for item in diff_dict["folder"]]
        diff_dict["files"].extend(str(Path(dcmp.left, item)) for item in files_names)

    elif dcmp.right_only:
        logging.error("Elements exist only in the modified folder but not in the original folder.")

def compare_subdirectory(sub_dcmp, folder_orig, folder_modf, thresh, diff_dict):
    """Compare files in a subdirectory and log the differences."""
    check_absent_elements(sub_dcmp, diff_dict)
    for filename in sub_dcmp.diff_files:
        file1_path = folder_orig / sub_dcmp.left / filename
        file2_path = folder_modf / sub_dcmp.right / filename
        diff_b_files = compare_files(file1_path, file2_path, thresh)
        # logging.warning("The different file is: %s\nThe difference information: %s", file1_path, diff_b_files)
        logging.warning("Different file: %s\nDifference information:\n%s",
                file1_path,
                json.dumps(diff_b_files, indent=2))
        if diff_b_files["critical_diff"]:
            diff_dict["files"].append(str(file1_path))
    for sub_subdir in sub_dcmp.subdirs.values():
        compare_subdirectory(sub_subdir, folder_orig, folder_modf, thresh, diff_dict)

def compare_folders(folder_orig, folder_modf, output_folder, thresh=2):
    """Compare two folders and log the differences."""
    configure_logging(Path(output_folder) / 'log.txt')

    folder_orig = Path(folder_orig)
    folder_modf = Path(folder_modf)
    output_folder = Path(output_folder) 
    if not output_folder.exists():
        output_folder.mkdir(parents=True) 
    diff_dict = {"folder": [], "files": []}

    dcmp = dircmp(folder_orig, folder_modf)
    dcmp.report_full_closure_to_log(logging.getLogger())
    logging.info(100 * "*")
    check_absent_elements(dcmp, diff_dict)

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(
            compare_subdirectory, sub_dcmp, folder_orig, folder_modf, thresh, diff_dict
        ) for sub_dcmp in dcmp.subdirs.values()]

    for future in futures:
        future.result()
    
    result = {"input_folders": {"folder_orig": str(folder_orig), "folder_modf": str(folder_modf)}, "result": diff_dict}
    result_file_path = output_folder / "result.json"
    with open(result_file_path, 'w') as result_file:
        json.dump(result, result_file, indent=2)

    return diff_dict

if __name__ == "__main__":
    original_folder = r"C:\Users\z004vw0y\Documents\python_folder\original_tests"
    new_folder =  r"C:\Users\z004vw0y\Documents\python_folder\modified_tests"
    out_folder = r"C:\Users\z004vw0y\Documents\python_folder\code_folder"

    result = compare_folders(original_folder, new_folder,out_folder)  
    print(result)