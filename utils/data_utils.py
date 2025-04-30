import csv

from models.job import Job


def is_duplicate_job(job_title: str, job_url: str, seen_jobs: set) -> bool:
    """Check if a job is a duplicate based on title and URL."""
    job_identifier = f"{job_title}:{job_url}"
    return job_identifier in seen_jobs


def is_complete_job(job: dict, required_keys: list) -> bool:
    """Check if a job has all the required fields."""
    return all(key in job for key in required_keys)


def save_jobs_to_csv(jobs: list, filename: str):
    """Save the extracted jobs to a CSV file."""
    if not jobs:
        print("No jobs to save.")
        return

    # Use field names from the Job model
    fieldnames = Job.model_fields.keys()

    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jobs)
    print(f"Saved {len(jobs)} jobs to '{filename}'.")
