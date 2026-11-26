import React, { useState, useEffect, useRef } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/AuthContext";
import { updateProfile, uploadStandardsFile, uploadStrategyFile, uploadAssetsFile } from "@/components/AIRecommender/api";
import { useToast } from "@/components/ui/use-toast";
import { Upload } from "lucide-react";

interface ProfileEditDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

export function ProfileEditDialog({ open, onOpenChange }: ProfileEditDialogProps) {
    const { user, refreshUser } = useAuth();
    const [firstName, setFirstName] = useState("");
    const [lastName, setLastName] = useState("");
    const [username, setUsername] = useState("");

    // New fields
    const [company, setCompany] = useState("");
    const [location, setLocation] = useState("");
    const [files, setFiles] = useState<File[]>([]);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Standards field
    const [standardsFiles, setStandardsFiles] = useState<File[]>([]);
    const standardsFileInputRef = useRef<HTMLInputElement>(null);

    // Assets field
    const [assetsFiles, setAssetsFiles] = useState<File[]>([]);
    const assetsFileInputRef = useRef<HTMLInputElement>(null);

    const [isLoading, setIsLoading] = useState(false);
    const { toast } = useToast();

    // Reset form when dialog opens or user changes
    useEffect(() => {
        if (open && user) {
            setFirstName(user.firstName || "");
            setLastName(user.lastName || "");
            setUsername(user.username || "");
            setCompany(user.company || "");
            setLocation(user.location || "");
            setFiles([]); // Reset files on open
            setStandardsFiles([]); // Reset standards files on open
            setAssetsFiles([]); // Reset assets files on open
        }
    }, [open, user]);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files?.length) {
            setFiles(Array.from(e.target.files));
        }
    };

    const removeFile = () => {
        setFiles([]);
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    }

    const handleStrategyFileUpload = async () => {
        if (!files.length) return;

        try {
            setIsLoading(true);

            // Upload each strategy file individually
            for (const file of files) {
                const result = await uploadStrategyFile(file);
                
                if (!result.success) {
                    throw new Error(result.message || `Failed to upload ${file.name}`);
                }
            }

            toast({
                title: "Strategy Document Uploaded",
                description: `${files.length} strategy file(s) uploaded successfully.`,
            });

            await refreshUser();

            // Clear the file after successful upload
            setFiles([]);
            if (fileInputRef.current) {
                fileInputRef.current.value = '';
            }
        } catch (error: any) {
            toast({
                title: "Upload Failed",
                description: error.message || "Failed to upload strategy document",
                variant: "destructive",
            });
        } finally {
            setIsLoading(false);
        }
    };

    const handleStandardsFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files?.length) {
            setStandardsFiles(Array.from(e.target.files));
        }
    };

    const handleAssetsFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files?.length) {
            setAssetsFiles(Array.from(e.target.files));
        }
    };

    const handleStandardsFileUpload = async () => {
        if (!standardsFiles.length) return;

        try {
            setIsLoading(true);

            // Upload each standards file individually
            for (const file of standardsFiles) {
                const result = await uploadStandardsFile(file);
                
                if (!result.success) {
                    throw new Error(result.message || `Failed to upload ${file.name}`);
                }
            }

            toast({
                title: "Standards Document Uploaded",
                description: `${standardsFiles.length} standards file(s) uploaded successfully.`,
            });

            await refreshUser();

            // Clear the file after successful upload
            setStandardsFiles([]);
            if (standardsFileInputRef.current) {
                standardsFileInputRef.current.value = '';
            }
        } catch (error: any) {
            toast({
                title: "Upload Failed",
                description: error.message || "Failed to upload standards document",
                variant: "destructive",
            });
        } finally {
            setIsLoading(false);
        }
    };

    const removeStandardsFile = () => {
        setStandardsFiles([]);
        if (standardsFileInputRef.current) {
            standardsFileInputRef.current.value = '';
        }
    }

    const handleAssetsFileUpload = async () => {
        if (!assetsFiles.length) return;

        try {
            setIsLoading(true);

            // Upload each assets file individually
            for (const file of assetsFiles) {
                const result = await uploadAssetsFile(file);
                
                if (!result.success) {
                    throw new Error(result.message || `Failed to upload ${file.name}`);
                }
            }

            toast({
                title: "Assets Document Uploaded",
                description: `${assetsFiles.length} assets file(s) uploaded successfully.`,
            });

            await refreshUser();

            // Clear the file after successful upload
            setAssetsFiles([]);
            if (assetsFileInputRef.current) {
                assetsFileInputRef.current.value = '';
            }
        } catch (error: any) {
            toast({
                title: "Upload Failed",
                description: error.message || "Failed to upload assets document",
                variant: "destructive",
            });
        } finally {
            setIsLoading(false);
        }
    };

    const removeAssetsFile = () => {
        setAssetsFiles([]);
        if (assetsFileInputRef.current) {
            assetsFileInputRef.current.value = '';
        }
    }

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsLoading(true);
        try {
            const formData = new FormData();
            formData.append('first_name', firstName);
            formData.append('last_name', lastName);
            formData.append('username', username);
            formData.append('company', company);
            formData.append('location', location);

            files.forEach((selectedFile) => formData.append('document', selectedFile));
            standardsFiles.forEach((selectedFile) => formData.append('standards_document', selectedFile));
            assetsFiles.forEach((selectedFile) => formData.append('assets_document', selectedFile));

            // Using 'any' cast as API expects specific object shape but backend supports FormData
            await updateProfile(formData as any);

            toast({
                title: "Profile Updated",
                description: "Your profile has been successfully updated.",
            });

            // Refresh user data in AuthContext without reloading the page
            await refreshUser();

        } catch (error: any) {
            toast({
                title: "Error",
                description: error.message || "Failed to update profile",
                variant: "destructive",
            });
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[550px] rounded-xl bg-gradient-to-br from-[#F5FAFC]/90 to-[#EAF6FB]/90 dark:from-slate-900/90 dark:to-slate-900/50 backdrop-blur-2xl border border-white/20 dark:border-slate-700/30 shadow-2xl transition-all duration-300 ease-in-out hover:scale-105 [&>button]:transition-all [&>button]:duration-200 [&>button]:hover:scale-[1.35] [&>button]:!top-6 [&>button]:!right-5 [&>button]:z-[100] max-h-[90vh] flex flex-col p-0 overflow-hidden">
                <form onSubmit={handleSubmit} className="flex flex-col flex-1 overflow-hidden min-h-0">
                    <div className="p-6 pb-4 flex-shrink-0 z-10 border-b border-black/5 dark:border-white/5">
                        <DialogHeader>
                            <DialogTitle className="text-2xl font-bold text-[#0F6CBD] dark:text-sky-300">Edit Profile</DialogTitle>
                            <DialogDescription className="text-muted-foreground/80">
                                Update your personal information here. Click save when you're done.
                            </DialogDescription>
                        </DialogHeader>
                    </div>

                    <div className="flex-1 overflow-y-auto custom-visible-scrollbar px-6 py-4">
                        <div className="grid gap-6">
                            <div className="grid grid-cols-4 items-center gap-4">
                                <Label htmlFor="username" className="text-center font-semibold text-[#0F6CBD] dark:text-sky-300">
                                    Username
                                </Label>
                                <Input
                                    id="username"
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    className="col-span-3 bg-white/50 dark:bg-slate-800/40 border-white/30 dark:border-slate-700/50 focus:border-[#0F6CBD] focus:ring-[#0F6CBD]/20 rounded-xl transition-all duration-200 hover:scale-[1.02]"
                                    placeholder="Enter username"
                                    required
                                />
                            </div>
                            <div className="grid grid-cols-4 items-center gap-4">
                                <Label htmlFor="firstName" className="text-center font-semibold text-[#0F6CBD] dark:text-sky-300">
                                    First Name
                                </Label>
                                <Input
                                    id="firstName"
                                    value={firstName}
                                    onChange={(e) => setFirstName(e.target.value)}
                                    className="col-span-3 bg-white/50 dark:bg-slate-800/40 border-white/30 dark:border-slate-700/50 focus:border-[#0F6CBD] focus:ring-[#0F6CBD]/20 rounded-xl transition-all duration-200 hover:scale-[1.02]"
                                    placeholder="Enter first name"
                                />
                            </div>
                            <div className="grid grid-cols-4 items-center gap-4">
                                <Label htmlFor="lastName" className="text-center font-semibold text-[#0F6CBD] dark:text-sky-300">
                                    Last Name
                                </Label>
                                <Input
                                    id="lastName"
                                    value={lastName}
                                    onChange={(e) => setLastName(e.target.value)}
                                    className="col-span-3 bg-white/50 dark:bg-slate-800/40 border-white/30 dark:border-slate-700/50 focus:border-[#0F6CBD] focus:ring-[#0F6CBD]/20 rounded-xl transition-all duration-200 hover:scale-[1.02]"
                                    placeholder="Enter last name"
                                />
                            </div>

                            {/* New Fields */}
                            <div className="grid grid-cols-4 items-center gap-4">
                                <Label htmlFor="company" className="text-center font-semibold text-[#0F6CBD] dark:text-sky-300">
                                    Company
                                </Label>
                                <Input
                                    id="company"
                                    value={company}
                                    onChange={(e) => setCompany(e.target.value)}
                                    className="col-span-3 bg-white/50 dark:bg-slate-800/40 border-white/30 dark:border-slate-700/50 focus:border-[#0F6CBD] focus:ring-[#0F6CBD]/20 rounded-xl transition-all duration-200 hover:scale-[1.02]"
                                    placeholder="Company"
                                />
                            </div>
                            <div className="grid grid-cols-4 items-center gap-4">
                                <Label htmlFor="location" className="text-center font-semibold text-[#0F6CBD] dark:text-sky-300">
                                    Location
                                </Label>
                                <Input
                                    id="location"
                                    value={location}
                                    onChange={(e) => setLocation(e.target.value)}
                                    className="col-span-3 bg-white/50 dark:bg-slate-800/40 border-white/30 dark:border-slate-700/50 focus:border-[#0F6CBD] focus:ring-[#0F6CBD]/20 rounded-xl transition-all duration-200 hover:scale-[1.02]"
                                    placeholder="Location"
                                />
                            </div>

                            {/* Strategy Document Upload */}
                            <div className="grid grid-cols-4 items-start gap-4">
                                <Label htmlFor="strategy" className="text-center font-semibold text-[#0F6CBD] dark:text-sky-300 pt-3">
                                    Strategy
                                </Label>
                                <div className="col-span-3 space-y-2">
                                    <div className="relative hover:scale-[1.02] transition-all duration-300">
                                        <div className="flex items-center bg-white/50 dark:bg-slate-800/40 border border-white/30 dark:border-slate-700/50 rounded-xl px-3 py-2 min-h-[40px]">
                                            <span className={`flex-1 text-sm ${files.length ? "text-foreground" : "text-muted-foreground"}`}>
                                                {files.length ? `${files.length} file(s) selected` : "Upload strategy document(s)"}
                                            </span>
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="sm"
                                                className="px-3 text-muted-foreground hover:text-foreground transition-colors hover:bg-transparent transition-transform hover:scale-110 active:scale-95"
                                                onClick={() => fileInputRef.current?.click()}
                                                title="Upload Strategy Document"
                                            >
                                                <Upload className={`h-4 w-4 ${files.length ? "text-primary" : ""}`} />
                                            </Button>
                                        </div>
                                        <Input
                                            type="file"
                                            ref={fileInputRef}
                                            className="hidden"
                                            onChange={handleFileChange}
                                            accept=".pdf,.docx,.doc,.txt,.png,.jpg,.jpeg,.csv"
                                            multiple
                                        />
                                    </div>
                                    {files.length > 0 && (
                                        <div className="flex items-center justify-between text-xs text-muted-foreground px-1">
                                            <span>{files.length} selected</span>
                                            <div className="flex gap-2">
                                                <button
                                                    type="button"
                                                    onClick={handleStrategyFileUpload}
                                                    disabled={isLoading}
                                                    className="text-blue-500 hover:text-blue-700 font-medium disabled:opacity-50"
                                                >
                                                    {isLoading ? "Uploading..." : "Upload"}
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={removeFile}
                                                    className="text-red-500 hover:text-red-700"
                                                >
                                                    Remove
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Standards Field with Upload */}
                            <div className="grid grid-cols-4 items-start gap-4">
                                <Label htmlFor="standards" className="text-center font-semibold text-[#0F6CBD] dark:text-sky-300 pt-3">
                                    Standards
                                </Label>
                                <div className="col-span-3 space-y-2">
                                    <div className="relative hover:scale-[1.02] transition-all duration-300">
                                        <div className="flex items-center bg-white/50 dark:bg-slate-800/40 border border-white/30 dark:border-slate-700/50 rounded-xl px-3 py-2 min-h-[40px]">
                                            <span className={`flex-1 text-sm ${standardsFiles.length ? "text-foreground" : "text-muted-foreground"}`}>
                                                {standardsFiles.length ? `${standardsFiles.length} file(s) selected` : "Upload standards document(s)"}
                                            </span>
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="sm"
                                                className="px-3 text-muted-foreground hover:text-foreground transition-colors hover:bg-transparent transition-transform hover:scale-110 active:scale-95"
                                                onClick={() => standardsFileInputRef.current?.click()}
                                                title="Upload Standards Document"
                                            >
                                                <Upload className={`h-4 w-4 ${standardsFiles.length ? "text-primary" : ""}`} />
                                            </Button>
                                        </div>
                                        <Input
                                            type="file"
                                            ref={standardsFileInputRef}
                                            className="hidden"
                                            onChange={handleStandardsFileChange}
                                            accept=".pdf,.docx,.doc,.txt,.png,.jpg,.jpeg"
                                            multiple
                                        />
                                    </div>
                                    {standardsFiles.length > 0 && (
                                        <div className="flex items-center justify-between text-xs text-muted-foreground px-1">
                                            <span>{standardsFiles.length} selected</span>
                                            <div className="flex gap-2">
                                                <button
                                                    type="button"
                                                    onClick={handleStandardsFileUpload}
                                                    disabled={isLoading}
                                                    className="text-blue-500 hover:text-blue-700 font-medium disabled:opacity-50"
                                                >
                                                    {isLoading ? "Uploading..." : "Upload"}
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={removeStandardsFile}
                                                    className="text-red-500 hover:text-red-700"
                                                >
                                                    Remove
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Assets Field with Upload */}
                            <div className="grid grid-cols-4 items-start gap-4">
                                <Label htmlFor="assets" className="text-center font-semibold text-[#0F6CBD] dark:text-sky-300 pt-3">
                                    Assets
                                </Label>
                                <div className="col-span-3 space-y-2">
                                    <div className="relative hover:scale-[1.02] transition-all duration-300">
                                        <div className="flex items-center bg-white/50 dark:bg-slate-800/40 border border-white/30 dark:border-slate-700/50 rounded-xl px-3 py-2 min-h-[40px]">
                                            <span className={`flex-1 text-sm ${assetsFiles.length ? "text-foreground" : "text-muted-foreground"}`}>
                                                {assetsFiles.length ? `${assetsFiles.length} file(s) selected` : "Upload assets document(s)"}
                                            </span>
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="sm"
                                                className="px-3 text-muted-foreground hover:text-foreground transition-colors hover:bg-transparent transition-transform hover:scale-110 active:scale-95"
                                                onClick={() => assetsFileInputRef.current?.click()}
                                                title="Upload Assets Document"
                                            >
                                                <Upload className={`h-4 w-4 ${assetsFiles.length ? "text-primary" : ""}`} />
                                            </Button>
                                        </div>
                                        <Input
                                            type="file"
                                            ref={assetsFileInputRef}
                                            className="hidden"
                                            onChange={handleAssetsFileChange}
                                            accept=".pdf,.csv,.docx,.xlsx,.txt"
                                            multiple
                                        />
                                    </div>
                                    {assetsFiles.length > 0 && (
                                        <div className="flex items-center justify-between text-xs text-muted-foreground px-1">
                                            <span>{assetsFiles.length} selected</span>
                                            <div className="flex gap-2">
                                                <button
                                                    type="button"
                                                    onClick={handleAssetsFileUpload}
                                                    disabled={isLoading}
                                                    className="text-blue-500 hover:text-blue-700 font-medium disabled:opacity-50"
                                                >
                                                    {isLoading ? "Uploading..." : "Upload"}
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={removeAssetsFile}
                                                    className="text-red-500 hover:text-red-700"
                                                >
                                                    Remove
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="p-6 pt-4 flex-shrink-0 border-t border-black/5 dark:border-white/5">
                        <DialogFooter className="gap-2 sm:gap-0">
                            <Button
                                type="button"
                                variant="outline"
                                onClick={() => onOpenChange(false)}
                                disabled={isLoading}
                                className="rounded-xl border-white/30 bg-white/20 hover:bg-white/40 dark:bg-slate-800/40 dark:hover:bg-slate-800/60 transition-all shadow-sm"
                            >
                                Cancel
                            </Button>
                            <Button
                                type="submit"
                                disabled={isLoading}
                                className="rounded-xl bg-[#2B95D6] hover:bg-[#064375] text-white font-semibold border border-white/30 transition-all duration-300 px-6 hover:scale-[1.02] active:scale-[0.98] shadow-none"
                            >
                                {isLoading ? "Saving..." : "Save"}
                            </Button>
                        </DialogFooter>
                    </div>
                </form>
            </DialogContent>
        </Dialog>
    );
}

