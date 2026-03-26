# Contributing to Octavia Code Review Agent

Thank you for considering contributing to this project!

## Getting Started

1. **Fork the repository**
2. **Clone your fork**
   ```bash
   git clone https://github.com/yourusername/code-review-agent.git
   cd code-review-agent
   ```
3. **Run the installation**
   ```bash
   ./install.sh
   ```

## Development Setup

### Configuration for Development

Create a `config.json` for your local environment:

```bash
cp config.sample.json config.json
# Edit config.json with your paths
```

**Note:** `config.json` is in `.gitignore` so your local settings won't be committed.

### Testing Your Changes

1. **Test configuration loading:**
   ```bash
   python3 config.py
   ```

2. **Verify setup:**
   ```bash
   ./setup_review_agent.sh
   ```

3. **Test Vertex AI connectivity:**
   ```bash
   ./test_agent.py
   ```

4. **Test with a real change:**
   ```bash
   ./review_single_change.py <change_number>
   ```

## Making Changes

### Code Style

- Follow PEP 8 for Python code
- Use meaningful variable names
- Add comments for complex logic
- Update documentation when changing features

### Commit Messages

Use clear, descriptive commit messages:

```
Add support for custom test commands

- Allow users to specify test commands in config.json
- Update config.sample.json with examples
- Document in README.md
```

### Pull Request Process

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes and commit:**
   ```bash
   git add .
   git commit -m "Description of changes"
   ```

3. **Push to your fork:**
   ```bash
   git push origin feature/your-feature-name
   ```

4. **Open a Pull Request** on GitHub

5. **Describe your changes:**
   - What problem does it solve?
   - How did you test it?
   - Any breaking changes?

## Areas for Contribution

### High Priority

- [ ] Support for additional OpenStack projects beyond Octavia
- [ ] Integration with Gerrit API to post reviews (with approval)
- [ ] Improved error handling and retry logic
- [ ] Performance optimizations for large changes

### Medium Priority

- [ ] Custom review templates
- [ ] Slack/email notifications when reviews complete
- [ ] Dashboard for review statistics
- [ ] Support for non-OpenStack Gerrit instances

### Low Priority

- [ ] Web UI for configuration
- [ ] Docker container for easy deployment
- [ ] GitHub Actions integration
- [ ] Support for other AI providers (Anthropic API, AWS Bedrock)

## Feature Requests

### Adding Support for New Projects

To adapt this agent for other projects (not just Octavia):

1. **Update repositories in `config.sample.json`:**
   ```json
   {
     "repositories": [
       "openstack/nova",
       "openstack/neutron"
     ]
   }
   ```

2. **Customize test commands:**
   ```json
   {
     "testing": {
       "unit_test_command": "pytest",
       "functional_test_command": "./run_tests.sh"
     }
   }
   ```

3. **Adjust review prompts** in `review_single_change.py` to include project-specific guidelines

### Adding New Analysis Checks

To add custom code analysis:

1. Edit the prompt in `review_single_change.py`
2. Add your specific checks in the "Code Quality Analysis" section
3. Update the review template to include new findings
4. Document in README.md

Example:
```python
## Step X: Custom Analysis
Check for:
- Your custom check 1
- Your custom check 2
```

## Testing Guidelines

### Manual Testing

Before submitting:

1. Test with at least 3 different changes
2. Verify all test types run correctly
3. Check review document formatting
4. Ensure no hardcoded paths remain

### Automated Testing

Currently, testing is manual. We welcome contributions for:
- Unit tests for config loading
- Integration tests for Gerrit API
- Mock tests for agent workflow

## Documentation

When adding features, update:

- **README.md** - Main documentation
- **QUICK_START.md** - Quick reference
- **config.sample.json** - Add new config options
- **Code comments** - Explain complex logic

## Questions?

- Open an issue for discussion
- Check existing issues for similar questions
- Review the documentation first

## Code of Conduct

- Be respectful and constructive
- Focus on the code, not the person
- Welcome newcomers
- Help others learn

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (MIT).

---

Thank you for contributing! 🚀
