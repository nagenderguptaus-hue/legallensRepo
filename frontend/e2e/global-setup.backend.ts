import { execFileSync } from 'node:child_process';
import { FIXTURES_DIR } from './fixtures';

/** Writes the synthetic demo documents (built by the backend's own factories) for upload. */
export default function globalSetup() {
  execFileSync('uv', ['run', '--directory', '../backend', 'python', 'scripts/make_fixtures.py', '--out', FIXTURES_DIR], {
    stdio: 'inherit',
  });
}
