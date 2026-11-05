"""Initial PostgreSQL application schema"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0001_application'
down_revision = None
branch_labels = None
depends_on = None


media_type = postgresql.ENUM('all', 'video', 'image', 'audio', 'document', name='mediatype', create_type=False)
job_stage = postgresql.ENUM('pending', 'exporting', 'filtering', 'downloading', 'completed', 'failed', 'cancelled', name='jobstage', create_type=False)
job_status = postgresql.ENUM('pending', 'running', 'completed', 'failed', 'cancelled', name='jobstatus', create_type=False)


def upgrade():
    for enum in (media_type, job_stage, job_status):
        enum.create(op.get_bind())
    op.create_table('download_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('rq_job_id', sa.String(length=128), nullable=True),
    sa.Column('rq_enqueued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('chat_id', sa.String(length=64), nullable=False),
    sa.Column('chat_title', sa.String(length=255), nullable=True),
    sa.Column('hashtag', sa.String(length=128), nullable=True),
    sa.Column('media_type', media_type, nullable=False),
    sa.Column('search_text', sa.String(length=255), nullable=True),
    sa.Column('date_from', sa.Date(), nullable=True),
    sa.Column('date_to', sa.Date(), nullable=True),
    sa.Column('skip_same', sa.Boolean(), nullable=False),
    sa.Column('refresh_export', sa.Boolean(), nullable=False),
    sa.Column('export_only', sa.Boolean(), nullable=False),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('output_subfolder', sa.String(length=128), nullable=False),
    sa.Column('export_json_path', sa.Text(), nullable=True),
    sa.Column('filtered_json_path', sa.Text(), nullable=True),
    sa.Column('download_path', sa.Text(), nullable=True),
    sa.Column('stage', job_stage, nullable=False),
    sa.Column('total_filtered_messages', sa.Integer(), nullable=False),
    sa.Column('total_downloaded_files', sa.Integer(), nullable=False),
    sa.Column('download_observed_files', sa.Integer(), nullable=False),
    sa.Column('download_observed_bytes', sa.BigInteger(), nullable=False),
    sa.Column('download_speed_bps', sa.BigInteger(), nullable=False),
    sa.Column('download_eta_seconds', sa.Integer(), nullable=True),
    sa.Column('status', job_status, nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('transfer_initialized', sa.Boolean(), nullable=False),
    sa.Column('total_failed_files', sa.Integer(), nullable=False),
    sa.Column('export_cursor', sa.Integer(), nullable=True),
    sa.Column('export_upper_id', sa.Integer(), nullable=True),
    sa.Column('operation_attempts', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('dedupe_key', sa.String(length=64), nullable=True),
    sa.Column('deletion_requested', sa.Boolean(), nullable=False),
    sa.Column('deletion_error', sa.Text(), nullable=True),
    sa.Column('deletion_rq_job_id', sa.String(length=128), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_download_jobs_chat_id'), 'download_jobs', ['chat_id'], unique=False)
    op.create_index(op.f('ix_download_jobs_id'), 'download_jobs', ['id'], unique=False)
    op.create_index(op.f('ix_download_jobs_rq_job_id'), 'download_jobs', ['rq_job_id'], unique=False)
    op.create_index('uq_download_jobs_active_dedupe', 'download_jobs', ['dedupe_key'], unique=True, postgresql_where=sa.text("status IN ('pending','running')"))
    op.create_table('download_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('chat_id', sa.String(length=64), nullable=True),
    sa.Column('chat_title', sa.String(length=255), nullable=True),
    sa.Column('hashtag', sa.String(length=128), nullable=True),
    sa.Column('media_type', media_type, nullable=False),
    sa.Column('search_text', sa.String(length=255), nullable=True),
    sa.Column('date_from', sa.Date(), nullable=True),
    sa.Column('date_to', sa.Date(), nullable=True),
    sa.Column('skip_same', sa.Boolean(), nullable=False),
    sa.Column('refresh_export', sa.Boolean(), nullable=False),
    sa.Column('export_only', sa.Boolean(), nullable=False),
    sa.Column('output_subfolder', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_download_templates_id'), 'download_templates', ['id'], unique=False)
    op.create_table('runtime_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('values_json', sa.Text(), nullable=False),
    sa.Column('pending_json', sa.Text(), nullable=True),
    sa.Column('operation_id', sa.String(length=32), nullable=True),
    sa.Column('operation_status', sa.String(length=24), nullable=False),
    sa.Column('operation_error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('download_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.String(length=64), nullable=False),
    sa.Column('message_id', sa.String(length=64), nullable=False),
    sa.Column('file_name', sa.Text(), nullable=False),
    sa.Column('message_json', sa.Text(), nullable=False),
    sa.Column('destination_root', sa.Text(), nullable=False),
    sa.Column('output_dir', sa.Text(), nullable=False),
    sa.Column('local_path', sa.Text(), nullable=True),
    sa.Column('expected_size', sa.BigInteger(), nullable=True),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['download_jobs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id', 'message_id')
    )
    op.create_index(op.f('ix_download_files_chat_id'), 'download_files', ['chat_id'], unique=False)
    op.create_index(op.f('ix_download_files_job_id'), 'download_files', ['job_id'], unique=False)
    op.create_index(op.f('ix_download_files_status'), 'download_files', ['status'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_download_files_status'), table_name='download_files')
    op.drop_index(op.f('ix_download_files_job_id'), table_name='download_files')
    op.drop_index(op.f('ix_download_files_chat_id'), table_name='download_files')
    op.drop_table('download_files')
    op.drop_table('runtime_settings')
    op.drop_index(op.f('ix_download_templates_id'), table_name='download_templates')
    op.drop_table('download_templates')
    op.drop_index('uq_download_jobs_active_dedupe', table_name='download_jobs', postgresql_where=sa.text("status IN ('pending','running')"))
    op.drop_index(op.f('ix_download_jobs_rq_job_id'), table_name='download_jobs')
    op.drop_index(op.f('ix_download_jobs_id'), table_name='download_jobs')
    op.drop_index(op.f('ix_download_jobs_chat_id'), table_name='download_jobs')
    op.drop_table('download_jobs')
    for enum in (job_status, job_stage, media_type):
        enum.drop(op.get_bind())
