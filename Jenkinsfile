
pipeline {
    agent {
        docker {
            image 'python:3.11-slim'
        }
    }

    options {
        skipDefaultCheckout(true)
        timestamps()
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Install dependencies') {
            steps {
                dir('backend') {
                    sh 'python --version'
                    sh 'python -m pip install --upgrade pip'
                    sh 'python -m pip install -e ".[dev]"'
                }
            }
        }

        stage('Ruff lint') {
            steps {
                dir('backend') {
                    sh 'ruff check .'
                }
            }
        }

        stage('Ruff format') {
            steps {
                dir('backend') {
                    sh 'ruff format --check .'
                }
            }
        }

        stage('Pytest') {
            steps {
                dir('backend') {
                    sh 'pytest'
                }
            }
        }
    }
}
