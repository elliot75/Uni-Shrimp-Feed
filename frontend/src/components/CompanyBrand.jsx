export function CompanyLogo({ className = '' }) {
    return (
        <div className={`shrink-0 rounded-lg bg-white p-2 ${className}`}>
            <img
                src="/uni-president-logo.png"
                alt="Uni-President"
                width="1740"
                height="1172"
                className="w-full h-auto"
            />
        </div>
    );
}

export function CopyrightNotice() {
    return (
        <footer className="px-4 py-4 text-center text-xs leading-relaxed muted">
            © {new Date().getFullYear()} UNI-PRESIDENT VIETNAM CO., LTD. All rights reserved.
        </footer>
    );
}
