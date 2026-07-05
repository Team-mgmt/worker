-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateEnum
CREATE TYPE "UserType" AS ENUM ('ADMIN', 'LIBRARIAN');

-- CreateEnum
CREATE TYPE "ShelfDetectionStatus" AS ENUM ('NORMAL', 'SUSPECTED_MISPLACEMENT', 'NEEDS_REVIEW', 'UNMATCHED');

-- CreateEnum
CREATE TYPE "EmailKind" AS ENUM ('VERIFY_EMAIL', 'RESET_PASSWORD', 'INVITATION', 'SYSTEM');

-- CreateTable
CREATE TABLE "Organization" (
    "id" UUID NOT NULL,
    "name" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "Organization_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "User" (
    "id" UUID NOT NULL,
    "name" TEXT NOT NULL,
    "phone" TEXT,
    "nickname" TEXT,
    "picture" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "OrganizationMember" (
    "id" UUID NOT NULL,
    "userId" UUID NOT NULL,
    "organizationId" UUID NOT NULL,
    "type" "UserType" NOT NULL,
    "name" TEXT NOT NULL,

    CONSTRAINT "OrganizationMember_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PermissionRelation" (
    "id" UUID NOT NULL,
    "name" TEXT NOT NULL,

    CONSTRAINT "PermissionRelation_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PermissionTuple" (
    "id" UUID NOT NULL,
    "label" TEXT NOT NULL DEFAULT '',
    "namespace" UUID NOT NULL,
    "objectId" UUID NOT NULL,
    "relationId" UUID NOT NULL,
    "memberId" UUID,
    "targetId" UUID,
    "organizationId" UUID NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "revokedAt" TIMESTAMP(3),
    "revokeReason" TEXT,

    CONSTRAINT "PermissionTuple_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Session" (
    "id" UUID NOT NULL,
    "userId" UUID NOT NULL,
    "providerConnectionId" UUID NOT NULL,
    "metadata" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expiresAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Session_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RefreshToken" (
    "id" UUID NOT NULL,
    "sessionId" UUID NOT NULL,
    "familyId" UUID NOT NULL,
    "tokenHash" TEXT NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "rotatedAt" TIMESTAMP(3),
    "rotatedFromId" UUID,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "revokedAt" TIMESTAMP(3),
    "revokedReason" TEXT,
    "metadata" JSONB NOT NULL,

    CONSTRAINT "RefreshToken_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Provider" (
    "id" UUID NOT NULL,
    "name" TEXT NOT NULL,
    "config" JSONB NOT NULL DEFAULT '{}',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "Provider_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ProviderConnection" (
    "id" UUID NOT NULL,
    "userId" UUID NOT NULL,
    "providerId" UUID NOT NULL,
    "providerUniqueId" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "data" JSONB NOT NULL,
    "primary" BOOLEAN NOT NULL DEFAULT false,
    "emailVerifiedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ProviderConnection_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "EmailVerificationToken" (
    "id" UUID NOT NULL,
    "providerConnectionId" UUID NOT NULL,
    "tokenHash" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "consumedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "EmailVerificationToken_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PasswordResetToken" (
    "id" UUID NOT NULL,
    "providerConnectionId" UUID NOT NULL,
    "tokenHash" TEXT NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "consumedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PasswordResetToken_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Invitation" (
    "id" UUID NOT NULL,
    "email" TEXT NOT NULL,
    "organizationId" UUID NOT NULL,
    "invitedById" UUID NOT NULL,
    "acceptedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "revokedAt" TIMESTAMP(3),

    CONSTRAINT "Invitation_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "UploadFile" (
    "id" UUID NOT NULL,
    "key" TEXT NOT NULL,
    "filename" TEXT NOT NULL,
    "contentType" TEXT NOT NULL,
    "size" INTEGER,
    "hash" TEXT,
    "createdById" UUID,
    "organizationId" UUID NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "finalizedAt" TIMESTAMP(3),

    CONSTRAINT "UploadFile_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "EmailLog" (
    "id" UUID NOT NULL,
    "userId" UUID,
    "organizationId" UUID,
    "kind" "EmailKind" NOT NULL,
    "toAddress" TEXT NOT NULL,
    "subject" TEXT NOT NULL,
    "transport" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "messageId" TEXT,
    "error" TEXT,
    "metadata" JSONB NOT NULL DEFAULT '{}',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "EmailLog_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Library" (
    "id" UUID NOT NULL,
    "code" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "address" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Library_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "LibraryBook" (
    "id" UUID NOT NULL,
    "isbn13" TEXT,
    "bookname" TEXT NOT NULL,
    "normalizedBookname" TEXT,
    "authors" TEXT,
    "normalizedAuthors" TEXT,
    "publisher" TEXT,
    "publicationYear" TEXT,
    "bookImageUrl" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "LibraryBook_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "LibraryHolding" (
    "id" UUID NOT NULL,
    "bookId" UUID,
    "libraryId" UUID NOT NULL,
    "libraryCode" TEXT NOT NULL,
    "classNo" TEXT,
    "classNoClean" TEXT,
    "classNoNum" DECIMAL(10,3),
    "bookCode" TEXT,
    "callNumber" TEXT,
    "normalizedCallNumber" TEXT,
    "shelfLocCode" TEXT,
    "shelfLocName" TEXT,
    "separateShelfCode" TEXT,
    "separateShelfName" TEXT,
    "copyCode" TEXT,
    "regDate" TIMESTAMP(3),
    "raw" JSONB NOT NULL DEFAULT '{}',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "LibraryHolding_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ShelfScanSession" (
    "id" UUID NOT NULL,
    "libraryId" UUID NOT NULL,
    "libraryCode" TEXT NOT NULL,
    "roomName" TEXT,
    "sourceName" TEXT,
    "sourceImageKey" TEXT,
    "sourceImageUrl" TEXT,
    "expectedShelfStart" DECIMAL(10,3),
    "expectedShelfEnd" DECIMAL(10,3),
    "estimatedShelfStart" DECIMAL(10,3),
    "estimatedShelfEnd" DECIMAL(10,3),
    "shelfConfidence" DECIMAL(5,4),
    "metadata" JSONB NOT NULL DEFAULT '{}',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ShelfScanSession_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ShelfDetection" (
    "id" UUID NOT NULL,
    "scanSessionId" UUID NOT NULL,
    "frameNo" INTEGER,
    "detectedOrder" INTEGER NOT NULL,
    "bbox" JSONB NOT NULL,
    "cropImageKey" TEXT,
    "cropImageUrl" TEXT,
    "ocrRawText" TEXT,
    "ocrTitle" TEXT,
    "ocrAuthor" TEXT,
    "ocrCallNumber" TEXT,
    "ocrConfidence" DECIMAL(5,4),
    "matchedBookId" UUID,
    "matchedHoldingId" UUID,
    "matchMethod" TEXT,
    "matchScore" DECIMAL(6,3),
    "scoreMargin" DECIMAL(6,3),
    "topCandidates" JSONB NOT NULL DEFAULT '[]',
    "status" "ShelfDetectionStatus" NOT NULL DEFAULT 'UNMATCHED',
    "reason" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ShelfDetection_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "Organization_deletedAt_idx" ON "Organization"("deletedAt");

-- CreateIndex
CREATE INDEX "Organization_name_idx" ON "Organization"("name");

-- CreateIndex
CREATE UNIQUE INDEX "User_nickname_key" ON "User"("nickname");

-- CreateIndex
CREATE INDEX "OrganizationMember_userId_idx" ON "OrganizationMember"("userId");

-- CreateIndex
CREATE INDEX "OrganizationMember_organizationId_idx" ON "OrganizationMember"("organizationId");

-- CreateIndex
CREATE INDEX "OrganizationMember_type_idx" ON "OrganizationMember"("type");

-- CreateIndex
CREATE INDEX "OrganizationMember_organizationId_type_idx" ON "OrganizationMember"("organizationId", "type");

-- CreateIndex
CREATE UNIQUE INDEX "OrganizationMember_userId_organizationId_key" ON "OrganizationMember"("userId", "organizationId");

-- CreateIndex
CREATE INDEX "PermissionTuple_namespace_objectId_idx" ON "PermissionTuple"("namespace", "objectId");

-- CreateIndex
CREATE INDEX "PermissionTuple_relationId_idx" ON "PermissionTuple"("relationId");

-- CreateIndex
CREATE INDEX "PermissionTuple_memberId_idx" ON "PermissionTuple"("memberId");

-- CreateIndex
CREATE INDEX "PermissionTuple_targetId_idx" ON "PermissionTuple"("targetId");

-- CreateIndex
CREATE INDEX "PermissionTuple_organizationId_idx" ON "PermissionTuple"("organizationId");

-- CreateIndex
CREATE INDEX "PermissionTuple_organizationId_namespace_objectId_idx" ON "PermissionTuple"("organizationId", "namespace", "objectId");

-- CreateIndex
CREATE INDEX "PermissionTuple_organizationId_relationId_idx" ON "PermissionTuple"("organizationId", "relationId");

-- CreateIndex
CREATE INDEX "PermissionTuple_organizationId_memberId_idx" ON "PermissionTuple"("organizationId", "memberId");

-- CreateIndex
CREATE INDEX "PermissionTuple_organizationId_targetId_idx" ON "PermissionTuple"("organizationId", "targetId");

-- CreateIndex
CREATE INDEX "Session_userId_idx" ON "Session"("userId");

-- CreateIndex
CREATE INDEX "Session_providerConnectionId_idx" ON "Session"("providerConnectionId");

-- CreateIndex
CREATE INDEX "RefreshToken_sessionId_idx" ON "RefreshToken"("sessionId");

-- CreateIndex
CREATE INDEX "RefreshToken_familyId_idx" ON "RefreshToken"("familyId");

-- CreateIndex
CREATE INDEX "RefreshToken_expiresAt_idx" ON "RefreshToken"("expiresAt");

-- CreateIndex
CREATE INDEX "RefreshToken_rotatedAt_idx" ON "RefreshToken"("rotatedAt");

-- CreateIndex
CREATE INDEX "RefreshToken_rotatedFromId_idx" ON "RefreshToken"("rotatedFromId");

-- CreateIndex
CREATE UNIQUE INDEX "RefreshToken_tokenHash_key" ON "RefreshToken"("tokenHash");

-- CreateIndex
CREATE INDEX "Provider_deletedAt_idx" ON "Provider"("deletedAt");

-- CreateIndex
CREATE INDEX "Provider_name_deletedAt_idx" ON "Provider"("name", "deletedAt");

-- CreateIndex
CREATE INDEX "ProviderConnection_userId_idx" ON "ProviderConnection"("userId");

-- CreateIndex
CREATE INDEX "ProviderConnection_providerId_idx" ON "ProviderConnection"("providerId");

-- CreateIndex
CREATE INDEX "ProviderConnection_email_idx" ON "ProviderConnection"("email");

-- CreateIndex
CREATE INDEX "ProviderConnection_providerId_providerUniqueId_idx" ON "ProviderConnection"("providerId", "providerUniqueId");

-- CreateIndex
CREATE UNIQUE INDEX "ProviderConnection_userId_providerId_key" ON "ProviderConnection"("userId", "providerId");

-- CreateIndex
CREATE UNIQUE INDEX "ProviderConnection_userId_primary_key" ON "ProviderConnection"("userId", "primary") WHERE ("primary" = true);

-- CreateIndex
CREATE UNIQUE INDEX "ProviderConnection_providerId_providerUniqueId_key" ON "ProviderConnection"("providerId", "providerUniqueId");

-- CreateIndex
CREATE UNIQUE INDEX "EmailVerificationToken_tokenHash_key" ON "EmailVerificationToken"("tokenHash");

-- CreateIndex
CREATE INDEX "EmailVerificationToken_providerConnectionId_idx" ON "EmailVerificationToken"("providerConnectionId");

-- CreateIndex
CREATE INDEX "EmailVerificationToken_expiresAt_idx" ON "EmailVerificationToken"("expiresAt");

-- CreateIndex
CREATE UNIQUE INDEX "PasswordResetToken_tokenHash_key" ON "PasswordResetToken"("tokenHash");

-- CreateIndex
CREATE INDEX "PasswordResetToken_providerConnectionId_idx" ON "PasswordResetToken"("providerConnectionId");

-- CreateIndex
CREATE INDEX "PasswordResetToken_expiresAt_idx" ON "PasswordResetToken"("expiresAt");

-- CreateIndex
CREATE INDEX "Invitation_organizationId_idx" ON "Invitation"("organizationId");

-- CreateIndex
CREATE INDEX "Invitation_invitedById_idx" ON "Invitation"("invitedById");

-- CreateIndex
CREATE INDEX "Invitation_email_acceptedAt_revokedAt_idx" ON "Invitation"("email", "acceptedAt", "revokedAt");

-- CreateIndex
CREATE UNIQUE INDEX "Invitation_email_organizationId_acceptedAt_key" ON "Invitation"("email", "organizationId", "acceptedAt");

-- CreateIndex
CREATE UNIQUE INDEX "UploadFile_key_key" ON "UploadFile"("key");

-- CreateIndex
CREATE INDEX "UploadFile_createdById_idx" ON "UploadFile"("createdById");

-- CreateIndex
CREATE INDEX "UploadFile_organizationId_idx" ON "UploadFile"("organizationId");

-- CreateIndex
CREATE INDEX "UploadFile_createdAt_idx" ON "UploadFile"("createdAt");

-- CreateIndex
CREATE INDEX "EmailLog_userId_idx" ON "EmailLog"("userId");

-- CreateIndex
CREATE INDEX "EmailLog_organizationId_idx" ON "EmailLog"("organizationId");

-- CreateIndex
CREATE INDEX "EmailLog_kind_idx" ON "EmailLog"("kind");

-- CreateIndex
CREATE INDEX "EmailLog_status_idx" ON "EmailLog"("status");

-- CreateIndex
CREATE INDEX "EmailLog_createdAt_idx" ON "EmailLog"("createdAt");

-- CreateIndex
CREATE UNIQUE INDEX "Library_code_key" ON "Library"("code");

-- CreateIndex
CREATE INDEX "Library_name_idx" ON "Library"("name");

-- CreateIndex
CREATE UNIQUE INDEX "LibraryBook_isbn13_key" ON "LibraryBook"("isbn13");

-- CreateIndex
CREATE INDEX "LibraryBook_bookname_idx" ON "LibraryBook"("bookname");

-- CreateIndex
CREATE INDEX "LibraryBook_normalizedBookname_idx" ON "LibraryBook"("normalizedBookname");

-- CreateIndex
CREATE INDEX "LibraryHolding_bookId_idx" ON "LibraryHolding"("bookId");

-- CreateIndex
CREATE INDEX "LibraryHolding_libraryId_idx" ON "LibraryHolding"("libraryId");

-- CreateIndex
CREATE INDEX "LibraryHolding_libraryCode_idx" ON "LibraryHolding"("libraryCode");

-- CreateIndex
CREATE INDEX "LibraryHolding_libraryCode_classNoNum_idx" ON "LibraryHolding"("libraryCode", "classNoNum");

-- CreateIndex
CREATE INDEX "LibraryHolding_libraryCode_normalizedCallNumber_idx" ON "LibraryHolding"("libraryCode", "normalizedCallNumber");

-- CreateIndex
CREATE INDEX "LibraryHolding_libraryCode_shelfLocName_idx" ON "LibraryHolding"("libraryCode", "shelfLocName");

-- CreateIndex
CREATE INDEX "ShelfScanSession_libraryId_idx" ON "ShelfScanSession"("libraryId");

-- CreateIndex
CREATE INDEX "ShelfScanSession_libraryCode_idx" ON "ShelfScanSession"("libraryCode");

-- CreateIndex
CREATE INDEX "ShelfScanSession_roomName_idx" ON "ShelfScanSession"("roomName");

-- CreateIndex
CREATE INDEX "ShelfScanSession_createdAt_idx" ON "ShelfScanSession"("createdAt");

-- CreateIndex
CREATE INDEX "ShelfDetection_scanSessionId_idx" ON "ShelfDetection"("scanSessionId");

-- CreateIndex
CREATE INDEX "ShelfDetection_detectedOrder_idx" ON "ShelfDetection"("detectedOrder");

-- CreateIndex
CREATE INDEX "ShelfDetection_matchedBookId_idx" ON "ShelfDetection"("matchedBookId");

-- CreateIndex
CREATE INDEX "ShelfDetection_matchedHoldingId_idx" ON "ShelfDetection"("matchedHoldingId");

-- CreateIndex
CREATE INDEX "ShelfDetection_status_idx" ON "ShelfDetection"("status");

-- AddForeignKey
ALTER TABLE "OrganizationMember" ADD CONSTRAINT "OrganizationMember_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "OrganizationMember" ADD CONSTRAINT "OrganizationMember_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PermissionTuple" ADD CONSTRAINT "PermissionTuple_relationId_fkey" FOREIGN KEY ("relationId") REFERENCES "PermissionRelation"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PermissionTuple" ADD CONSTRAINT "PermissionTuple_memberId_fkey" FOREIGN KEY ("memberId") REFERENCES "OrganizationMember"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PermissionTuple" ADD CONSTRAINT "PermissionTuple_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PermissionTuple" ADD CONSTRAINT "PermissionTuple_targetId_fkey" FOREIGN KEY ("targetId") REFERENCES "PermissionTuple"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Session" ADD CONSTRAINT "Session_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Session" ADD CONSTRAINT "Session_providerConnectionId_fkey" FOREIGN KEY ("providerConnectionId") REFERENCES "ProviderConnection"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "RefreshToken" ADD CONSTRAINT "RefreshToken_sessionId_fkey" FOREIGN KEY ("sessionId") REFERENCES "Session"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "RefreshToken" ADD CONSTRAINT "RefreshToken_rotatedFromId_fkey" FOREIGN KEY ("rotatedFromId") REFERENCES "RefreshToken"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProviderConnection" ADD CONSTRAINT "ProviderConnection_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProviderConnection" ADD CONSTRAINT "ProviderConnection_providerId_fkey" FOREIGN KEY ("providerId") REFERENCES "Provider"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "EmailVerificationToken" ADD CONSTRAINT "EmailVerificationToken_providerConnectionId_fkey" FOREIGN KEY ("providerConnectionId") REFERENCES "ProviderConnection"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PasswordResetToken" ADD CONSTRAINT "PasswordResetToken_providerConnectionId_fkey" FOREIGN KEY ("providerConnectionId") REFERENCES "ProviderConnection"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Invitation" ADD CONSTRAINT "Invitation_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Invitation" ADD CONSTRAINT "Invitation_invitedById_fkey" FOREIGN KEY ("invitedById") REFERENCES "OrganizationMember"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "UploadFile" ADD CONSTRAINT "UploadFile_createdById_fkey" FOREIGN KEY ("createdById") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "UploadFile" ADD CONSTRAINT "UploadFile_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "EmailLog" ADD CONSTRAINT "EmailLog_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "EmailLog" ADD CONSTRAINT "EmailLog_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LibraryHolding" ADD CONSTRAINT "LibraryHolding_bookId_fkey" FOREIGN KEY ("bookId") REFERENCES "LibraryBook"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LibraryHolding" ADD CONSTRAINT "LibraryHolding_libraryId_fkey" FOREIGN KEY ("libraryId") REFERENCES "Library"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ShelfScanSession" ADD CONSTRAINT "ShelfScanSession_libraryId_fkey" FOREIGN KEY ("libraryId") REFERENCES "Library"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ShelfDetection" ADD CONSTRAINT "ShelfDetection_scanSessionId_fkey" FOREIGN KEY ("scanSessionId") REFERENCES "ShelfScanSession"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ShelfDetection" ADD CONSTRAINT "ShelfDetection_matchedBookId_fkey" FOREIGN KEY ("matchedBookId") REFERENCES "LibraryBook"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ShelfDetection" ADD CONSTRAINT "ShelfDetection_matchedHoldingId_fkey" FOREIGN KEY ("matchedHoldingId") REFERENCES "LibraryHolding"("id") ON DELETE SET NULL ON UPDATE CASCADE;
