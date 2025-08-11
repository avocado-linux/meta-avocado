# Repository Monitoring System

This directory contains an automated monitoring system that watches for build completion in Yocto deploy directories and automatically updates RPM repository metadata.

## Overview

The monitoring system watches for build completion markers and automatically triggers repository metadata regeneration when:
- The `avocado-build.done` file is created or updated after a successful build
- Initial setup when the container starts and finds existing repositories

## Components

### Core Scripts

1. **`monitor-repo.sh`** - Efficient monitoring that watches for build completion marker file
2. **`setup-repo.sh`** - Repository setup script that processes the map file and creates metadata
3. **`entrypoint.sh`** - Container entrypoint that starts monitoring and nginx

### Build Integration

**`avocado-complete.bb`** - Modified Yocto recipe that writes `avocado-build.done` file after successful build completion

### Configuration Files

1. **`Containerfile`** - Updated to include `inotify-tools` package
2. **`compose.yml`** - Updated to support monitoring configuration

## Usage

### Docker Compose

Repository monitoring is enabled by default when using Docker Compose:

```bash
# Start with monitoring enabled (default)
docker-compose up

# Disable monitoring completely
ENABLE_MONITORING=false docker-compose up

# Custom configuration
ENABLE_MONITORING=true \
CHECK_INTERVAL=5 \
LOG_LEVEL=DEBUG \
docker-compose up
```

### Direct Script Usage

```bash
# Repository monitoring
./monitor-repo.sh /path/to/deploy/dir

# With custom configuration
CHECK_INTERVAL=5 \
LOG_LEVEL=DEBUG \
DRY_RUN=true \
./monitor-repo.sh /path/to/deploy/dir
```

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_MONITORING` | `true` | Enable/disable automatic monitoring |
| `CHECK_INTERVAL` | `2` | Seconds between done-file checks |
| `LOG_LEVEL` | `INFO` | Logging level: DEBUG, INFO, WARN, ERROR |
| `DRY_RUN` | `false` | Log changes without actually updating |

### Volume Mounts

The repository directory must be mounted as a volume for monitoring to work:

```yaml
volumes:
  - ${DEPLOY_DIR}/rpm:/repo:ro  # Read-only mount for security
```

**Note:** Even with a read-only mount, the monitoring system can detect changes made to the source directory on the host.

## How It Works

### Repository Monitoring Process

1. **Build Integration**: The `avocado-complete.bb` recipe writes `avocado-build.done` after successful build
2. **Startup**: The monitoring script checks for existing done files and performs initial setup
3. **Monitoring**: Efficiently watches only for the done file using `inotify` or polling
4. **Trigger**: When done file is created/updated, repository metadata is regenerated
5. **Cleanup**: Done file is archived to prevent re-triggering

### Monitored Events

- **Build Completion**: Creation or modification of `avocado-build.done` file
- **Initial Setup**: Existing repositories when container starts

### Update Triggers

The system triggers repository metadata updates when:
- Build completion marker file is created or updated
- Container starts and finds existing repository structure

## Features

### Repository Monitor (`monitor-repo.sh`)

- **Build Completion Detection**: Watches for `avocado-build.done` file creation/updates
- **Efficient Monitoring**: Uses `inotify` when available, falls back to polling
- **Automatic Repository Regeneration**: Triggers `setup-repo.sh` when builds complete
- **Graceful Shutdown**: Proper signal handling for clean container stops
- **Configurable Logging**: Multiple log levels with detailed information
- **Dry Run Mode**: Test changes without actually updating repositories
- **Performance Tracking**: Monitors update duration and timing
- **File Archiving**: Moves processed done files to prevent re-triggering

## Troubleshooting

### Common Issues

1. **Monitoring Not Starting**
   ```bash
   # Check if inotify-tools is installed
   docker exec <container> which inotifywait

   # Check container logs
   docker logs <container>
   ```

2. **Updates Not Triggering**
   ```bash
   # Enable debug logging
   LOG_LEVEL=DEBUG docker-compose up

   # Check file permissions
   docker exec <container> ls -la /repo
   ```

3. **Performance Issues**
   ```bash
   # Increase batch window to reduce update frequency
   BATCH_UPDATE_WINDOW=60 docker-compose up

   # Use basic monitor for lower resource usage
   # Edit entrypoint.sh to use monitor-repo-changes.sh
   ```

### Monitoring Health

Check monitoring status:
```bash
# View real-time logs
docker logs -f <container>

# Check process status
docker exec <container> ps aux | grep monitor

# Test with dry run
DRY_RUN=true docker-compose up
```

## Security Considerations

- Repository directory is mounted read-only for security
- Monitoring process runs with minimal privileges
- Input validation prevents malformed map files from causing issues
- Signal handlers ensure graceful shutdown

## Performance Impact

- **CPU**: Minimal overhead from `inotify` watching
- **Memory**: Small footprint for event processing
- **Disk I/O**: Repository updates only when necessary
- **Network**: No additional network overhead

## Integration with Existing Workflows

The monitoring system is designed to be backward compatible:
- Existing build processes continue to work unchanged
- Manual repository setup still functions
- Monitoring can be disabled if not needed
- No changes required to map file format or structure

## Future Enhancements

Potential improvements:
- Web dashboard for monitoring status
- Prometheus metrics integration
- Webhook notifications for updates
- Selective monitoring of specific directories
- Integration with CI/CD pipelines
